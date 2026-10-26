"""G2-P3-I1-C3: MASFactory implementation of the author workflow."""
import argparse
import json
import os
import re
import tiktoken
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock

from masfactory import Agent, CustomNode, LegacyOpenAIModel, Loop, MessageFormatter, NodeTemplate, RootGraph


# 1. Defaults; command-line arguments control data paths and request settings.
MODEL = "gpt-4o-mini"
MAX_ROUNDS = 10
AGENT_WORKERS = None
INVOKE_ATTEMPTS = 3
AUTHOR_ERRORS = False
PARSE_STRICT = True
AGENT_MAX_RETRIES = 1

# 与作者 predict_with_agent 中的提示词相同。
INSTRUCTION = "You are tasked with evaluating the truth of a given claim. You must base your judgment solely on available evidence and previous conversation information. Do not use any knowledge or information from your own model-based understanding or internal training data. Your judgment should rely entirely on the facts and evidence presented, and you should not infer beyond what is directly supported by those sources. "
OUTPUT_REQUIREMENTS = "Please strictly follow this format:\nResult: <Your answer from one of these three options: supporting, neutral, refuting>\nExplanation: <Brief explanation of why you made this choice>"


# 与作者一样，用tiktoken统计提示词正文和原始回复；不是服务商账单usage。
# 所有角色、所有阶段共用模型，成功返回的提示词和回复都会计入。
class CountedModel(LegacyOpenAIModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.encoder = tiktoken.encoding_for_model("gpt-4o")
        self.input_tokens = 0
        self.output_tokens = 0
        self.token_lock = Lock()

    def invoke(self, messages, tools=None, settings=None, **kwargs):
        kwargs.setdefault("max_retries", INVOKE_ATTEMPTS)
        response = super().invoke(messages, tools, settings, **kwargs)
        # 本脚本最后一条消息是user提示词；content是尚未经过formatter解析的回复。
        input_count = len(self.encoder.encode(messages[-1]["content"]))
        output_count = len(self.encoder.encode(response["content"]))
        with self.token_lock:
            self.input_tokens += input_count
            self.output_tokens += output_count
        return response



# 2. Formatter 只做文本转换。这里三种作者脚本都用 json.dumps(indent=2)。
class AuthorFormatter(MessageFormatter):
    def __init__(self, prediction=False):
        super().__init__()
        self.prediction = prediction
        self._is_input_formatter = self._is_output_formatter = True
        self._agent_introducer = OUTPUT_REQUIREMENTS if prediction else "Return the response text."

    def dump(self, message):
        if isinstance(message, str):
            return message  # 保持空的 system 消息，不添加额外指令。
        return json.dumps(message["prompt"], indent=2)

    def format(self, message):
        if not self.prediction:
            return {"text": message}  # 摘要、选人、说服和 instructor 回复交给对应节点处理。
        result = re.search(r"Result:\s*(.*)", message)
        explanation = re.search(r"Explanation:\s*(.*)", message)
        judgement = ((result.group(1).strip() if result else "") or message).lower()
        if judgement not in ("supporting", "neutral", "refuting"):
            raise ValueError(f"无法解析模型的判断：{message}")
        return {"judgement": judgement,
                "explanation": explanation.group(1).strip() if explanation else ""}


def make_agent(name, model, prediction=False):
    # 各种角色配置相同，只把这一段重复的 Agent 构造放在函数里。
    agent = Agent(
        name=name, model=model, instructions="", prompt_template="",
        formatters=AuthorFormatter(prediction), hide_unused_fields=False,
        memories=[], pull_keys={}, push_keys={}, max_retries=1,
    )
    agent.build()
    return agent


def terminate_cond(message, attrs):
    return message["done"]


# 3. controller → speak → decide → update_context → controller
# G2 不投票：最终结论、下一轮谁发言，都由 Instructor 决定。
def build_graph(sample, model):
    names = [f"Agent{i}" for i in range(1, len(sample["sentences_and_labels"]) + 1)]
    agents = {name: make_agent(name, model, prediction=True) for name in names}
    instructor = make_agent("Instructor", model)
    input_data = {
        "claim": sample["claim"],
        "evidences": {name: item["sentence"]
                      for name, item in zip(names, sample["sentences_and_labels"])},
        "histories": {name: [] for name in names}, "instructor_history": [],
        "predictions": {name: {"judgement": "", "explanation": ""} for name in names},
        "current_predictions": {}, "selected": list(names),
        "done": False, "prediction": "", "rounds": 0, "actual_rounds": 0,
        "last_votes": {}, "decision_reason": "", "instructor_response": "",
    }

    def speak(d, attrs):
        current_round = attrs["current_iteration"]
        print(f"  第{current_round}轮发言者：{d['selected']}")

        def predict(name):
            prompt = {
                "instruction": INSTRUCTION, "claim": d["claim"],
                "evidence": d["evidences"][name],
                "previous conversation information": d["histories"][name],
                "Output requirements": OUTPUT_REQUIREMENTS,
            }
            return agents[name].step({"prompt": prompt})

        current = {}
        # I1：同一轮并行，各 Agent 看不到本轮其他人刚生成的发言。
        with ThreadPoolExecutor(max_workers=AGENT_WORKERS) as pool:
            futures = {pool.submit(predict, name): name for name in d["selected"]}
            for future in as_completed(futures):
                current[futures[future]] = future.result()
        d["predictions"].update(current)
        d["current_predictions"] = current
        d["actual_rounds"] = current_round
        d["last_votes"] = {name: reply["judgement"] for name, reply in d["predictions"].items()}
        return d

    def decide(d, attrs):
        prompt = {
            "instruction": "You are an instructor overseeing multiple agents and your task is to judge the claim's truthfulness.Please review the rationale for each judgement, as well as relevant previous conversation. Assess whether whether the claim's truthfulness can be judged or if further discussion or information is needed.",
            "claim": d["claim"], "previous conversation": d["instructor_history"],
            "current round agent judgements": d["current_predictions"],
            "previous agent judgements": {name: d["predictions"][name] for name in names if name not in d["current_predictions"]},
            "output requirements": "Your response should indicate one of the following:\nFinal Decision: The judgement (Please choose from these three answers: supporting, neutral, refuting)\nNeed Further Discussion: More information or clarification is needed before making a final decision.\nPlease provide a brief explanation for your choice.",
        }
        response = instructor.step({"prompt": prompt})["text"]
        d["instructor_response"] = response
        # 保留作者解析方式：先看 Need Further Discussion，再取 Final Decision 行。
        match = re.search(r"Final Decision:\s*(.*)", response)
        decision = match.group(1).strip() if match and "Need Further Discussion" not in response else ""
        d["prediction"] = decision
        d["done"] = bool(decision)
        if decision:
            d["rounds"] = attrs["current_iteration"]
            d["decision_reason"] = "instructor_decision"
        print(f"  Instructor：{decision or '继续讨论'}")
        return d

    def update_context(d, attrs):
        if d["done"]:
            return d  # 已有最终结论，不再生成摘要和选择下一轮。
        current_round = attrs["current_iteration"]
        summary_prompt = {
            "instruction": "You are an instructor overseeing multiple agents and tasked with evaluating the truth of a given claim. Based on the previous conversation and the judgments from the current round, please generate a comprehensive summary that highlights the key evidence, important information, and judgment outcomes relevant to claim verification, focusing on the historical context that contributes to the assessment of the claim's truthfulness.",
            "claim": d["claim"], "previous conversation": d["instructor_history"],
            "current round judgments": d["current_predictions"],
        }
        summary = instructor.step({"prompt": summary_prompt})["text"]
        # 修正作者 update_history 的实参错位：message 放摘要，round 放整数轮数。
        history = [{"name": "instructor", "task": "Instructor", "message": summary, "round": current_round}]
        d["instructor_history"] = history
        d["histories"] = {name: list(history) for name in names}
        selection_prompt = {
            "instruction": "You are an instructor overseeing multiple assistants and tasked with evaluating the truth of a given claim. Based on their judgments and explanations, as well as the previous conversation provided, please decide which agents should speak in the next round and the order in which they will speak.",
            "claim": d["claim"], "previous conversation": history,
            "assistants information": {name: d["predictions"][name] for name in names},
            "output requirements": "Please provide the names of the agents in the order they should speak.\nPlease strictly follow this format:\nAgentNames: [AgentX, AgentY, ...] (where X, Y, ... are the agent numbers)",
        }
        response = instructor.step({"prompt": selection_prompt})["text"]
        chosen = re.findall(r"Agent(\d+)", response)
        d["selected"] = sorted((name for name in names if name[5:] in chosen),
                               key=lambda name: chosen.index(name[5:]))
        # 与作者一致：第十轮没有最终结论，也会先摘要、选人，然后退出。
        # 不添加多数票兜底；作者此时返回空字符串、rounds=0。
        if not d["selected"] or current_round >= MAX_ROUNDS:
            d["done"] = True
            d["decision_reason"] = "no_next_agents" if not d["selected"] else "max_rounds_without_decision"
        return d

    steps = [("speak", speak), ("decide", decide), ("update_context", update_context)]

    # 每条边传递同一组字段，节点只修改自己负责的部分。
    # histories/claim/evidences 也随反馈边回到 controller，不会在第二轮丢失。
    fields = {key: "" for key in input_data}
    nodes = [(name, NodeTemplate(CustomNode, forward=forward,
                                pull_keys={"current_iteration": "当前轮数"}, push_keys={}))
             for name, forward in steps]
    route = ["controller"] + [name for name, _ in steps] + ["controller"]
    edges = [(source, target, dict(fields)) for source, target in zip(route, route[1:])]
    discussion = NodeTemplate(Loop, max_iterations=MAX_ROUNDS,
                              terminate_condition_function=terminate_cond, nodes=nodes, edges=edges)
    result_fields = {"prediction": "", "rounds": "", "last_votes": "", "decision_reason": ""}
    result_fields.update(actual_rounds="", instructor_response="")
    graph = RootGraph(
        name="G2-P3-I1-C3-simple", nodes=[("discussion", discussion)],
        edges=[("entry", "discussion", fields), ("discussion", "exit", result_fields)],
    )
    graph.build()
    return graph, input_data


# 4. Read data -> run one graph per claim -> save results.
def main():
    global AGENT_WORKERS, INVOKE_ATTEMPTS, AUTHOR_ERRORS, PARSE_STRICT
    parser = argparse.ArgumentParser(description="G2-P3-I1-C3 claim verification")
    parser.add_argument("--data", type=Path, required=True, help="Processed JSON keyed by claim ID")
    parser.add_argument("--limit", type=int, default=0, help="First N selected claims; 0 means all")
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based offset in dataset order")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "results/G2-P3-I1-C3")
    parser.add_argument("--resume", type=Path, help="Resume this result JSON; saved claims are skipped")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--sdk-retries", type=int, default=1000000,
                        help="OpenAI SDK retry limit; historical default is large, 0 disables SDK retries")
    parser.add_argument("--invoke-attempts", type=int, default=3,
                        help="MASFactory adapter attempts per invocation, including the first")
    parser.add_argument("--agent-workers", type=int, help="Thread count for parallel stages only")
    parser.add_argument("--on-error", choices=("stop", "record"), default="stop",
                        help="Stop on a failed claim, or save an empty prediction and continue")

    args = parser.parse_args()
    if args.limit < 0 or args.start_index < 0 or args.sdk_retries < 0 or args.invoke_attempts < 1 or args.timeout <= 0:
        parser.error("Limits/retries must be nonnegative; timeout and invoke-attempts must be positive")
    if args.agent_workers is not None and args.agent_workers < 1:
        parser.error("agent-workers must be positive")
    AGENT_WORKERS = args.agent_workers
    INVOKE_ATTEMPTS = args.invoke_attempts

    data = json.loads(args.data.read_text(encoding="utf-8"))
    results = json.loads(args.resume.read_text(encoding="utf-8")) if args.resume else {}
    for claim_id, row in results.items():
        if claim_id not in data or row["correct_answer"] != data[claim_id]["labels"]:
            raise ValueError(f"Resume result does not match the dataset: {claim_id}")
    samples = list(data.items())[args.start_index:]
    if args.limit:
        samples = samples[:args.limit]
    pending = [(claim_id, sample) for claim_id, sample in samples if claim_id not in results]
    if not pending:
        print("No pending claims; no model requests made.")
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_path = args.resume or args.output_dir / f"mas_G2-P3-I1-C3_{timestamp}.json"
    if output_path.resolve() == args.data.resolve():
        parser.error("The result path must not overwrite the dataset")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Results: {output_path}; pending claims: {len(pending)}; model: {args.model}")
    model = CountedModel(model_name=args.model, api_key=os.getenv("OPENAI_API_KEY"),
                         base_url=os.getenv("OPENAI_BASE_URL"), timeout=args.timeout,
                         max_retries=args.sdk_retries)
    for claim_id, sample in pending:
        print(f"Claim {claim_id}")
        model.input_tokens = model.output_tokens = 0
        graph, input_data = build_graph(sample, model)
        try:
            out, _ = graph.invoke(input_data)
        except Exception as error:
            if args.on_error == "stop":
                raise
            # Keep failed attempts in the denominator; never manufacture a valid label.
            out = {"prediction": "", "rounds": 0, "actual_rounds": 0,
                   "instructor_response": "", "last_votes": {}, "decision_reason": "request_or_workflow_error"}
            print(f"Claim {claim_id} failed: {type(error).__name__}")
        results[claim_id] = {'judgement': out['prediction'], 'correct_answer': sample['labels'], 'rounds': out['rounds'], 'actual_rounds': out['actual_rounds'], 'instructor_response': out['instructor_response'], 'correct': out['prediction'].strip().lower() == sample['labels'].strip().lower(), 'input_tokens': model.input_tokens, 'output_tokens': model.output_tokens, 'last_votes': out['last_votes'], 'decision_reason': out['decision_reason']}
        results[claim_id]["run_settings"] = {
            "strategy": "G2-P3-I1-C3", "model": args.model,
            "timeout": args.timeout, "sdk_retries": args.sdk_retries,
            "invoke_attempts": args.invoke_attempts, "agent_workers": args.agent_workers,
            "on_error": args.on_error, "author_errors": AUTHOR_ERRORS,
            "strict_parse": PARSE_STRICT,
        }
        # Replace only after a complete JSON has been written.
        temporary_path = output_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(output_path)
        print(f"{claim_id}: {out['prediction']}; gold: {sample['labels']}")
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
