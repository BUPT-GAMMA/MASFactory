"""G1-P2-I4-C2: MASFactory implementation of the author workflow."""
import argparse
import json
import os
import re
import tiktoken
from collections import Counter
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
# 与作者 Agent.generate_history 中的指令相同；{name} 换成发言者自己的编号。
SUMMARY_INSTRUCTION = "You are {name}. Based on the previous conversation and the judgments from the current round, please generate a comprehensive summary that highlights the key evidence, important information, and judgment outcomes relevant to claim verification, focusing on the historical context that contributes to the assessment of the claim's truthfulness."


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


# 3. 每个样本建一个图，d 是沿着这一轮各节点传递的数据字典。
# controller → communicate → judge → collect → update_context → controller
def build_graph(sample, model):
    names = [f"Agent{i}" for i in range(1, len(sample["sentences_and_labels"]) + 1)]
    agents = {name: make_agent(name, model, prediction=True) for name in names}
    selectors = {name: make_agent(name + "-select", model) for name in names}
    summarizers = {name: make_agent(name + "-summary", model) for name in names}
    # 每个 sender/target 使用单独的 Agent 对象，避免并行调用同一对象的 step。
    persuaders = {(name, target): make_agent(name + "-to-" + target, model)
                  for name in names for target in names}
    input_data = {
        "claim": sample["claim"],
        "evidences": {name: item["sentence"]
                      for name, item in zip(names, sample["sentences_and_labels"])},
        "histories": {name: [] for name in names},
        "predictions": {}, "current_predictions": {}, "persuasions": {},
        "unanimous": False, "done": False, "prediction": "", "rounds": 0,
        "last_votes": {}, "decision_reason": "",
    }

    def communicate(d, attrs):
        # 第一轮先各自判断，从第二轮才选择说服对象并发送说服内容。
        if attrs["current_iteration"] == 1:
            return d

        def persuade(name):
            prompt = {
                "instruction": f"You are {name}, and you need to reach a consensus with other agents to determine the truth of a claim. If other agents have different judgements from you and the evidence is insufficient, you should persuade them to change their judgment to increase the chances of your judgement winning. Please decide whether you need to communicate with any agent based on the judgment of other agents.",
                "claim": d["claim"],
                "your judgement": d["predictions"][name],
                "other judgement": {other: d["predictions"][other] for other in names if other != name},
                "previous conversation information": d["histories"][name],
                "Output requirements": "Your response should indicate one of the following:\nYes.AgentNames: [AgentX, AgentY, ...] (where X, Y, ... are the agent numbers)\nNo.",
            }
            response = selectors[name].step({"prompt": prompt})["text"]
            chosen = re.findall(r"Agent(\d+)", response) if "yes" in response.lower() else []
            # 与作者一样按原编号筛选、去重；不额外排除模型选出的自己。
            targets = [target for target in names if target[5:] in chosen]

            def send(target):
                prompt = {
                    "instruction": f"You are {name}, please leave your judgement to {target}. You should deliver your judgement once you are confident enough and in a way to convince other agent with a short reason.",
                    "claim": d["claim"], "your judgement": d["predictions"][name],
                    "his judgement": d["predictions"][target],
                    "previous conversation information": d["histories"][name],
                }
                return persuaders[name, target].step({"prompt": prompt})["text"]

            messages = {}
            with ThreadPoolExecutor(max_workers=AGENT_WORKERS) as pool:
                futures = {pool.submit(send, target): target for target in targets}
                for future in as_completed(futures):
                    messages[futures[future]] = future.result()
            return messages

        persuasions = {}
        with ThreadPoolExecutor(max_workers=AGENT_WORKERS) as pool:
            futures = {pool.submit(persuade, name): name for name in names}
            for future in as_completed(futures):
                sender = futures[future]
                for target, text in future.result().items():
                    persuasions.setdefault(target, {})[sender] = text
        d["persuasions"] = persuasions
        return d

    def judge(d, attrs):
        first_round = attrs["current_iteration"] == 1
        selected = names if first_round else [name for name in names if name in d["persuasions"]]

        def predict(name):
            instruction = INSTRUCTION if first_round else INSTRUCTION.replace(
                "available evidence and previous", "available evidence, persuasion from other agents and previous")
            prompt = {"instruction": instruction, "claim": d["claim"], "evidence": d["evidences"][name]}
            if not first_round:
                prompt["persuasion from other agents"] = d["persuasions"][name]
            prompt["previous conversation information"] = d["histories"][name]
            prompt["Output requirements"] = OUTPUT_REQUIREMENTS
            return agents[name].step({"prompt": prompt})

        current = {}
        with ThreadPoolExecutor(max_workers=AGENT_WORKERS) as pool:
            futures = {pool.submit(predict, name): name for name in selected}
            for future in as_completed(futures):
                current[futures[future]] = future.result()
        # 没收到说服的 Agent 保留原判断。第一轮按完成顺序，之后按编号合并。
        previous = {**d["predictions"], **current}
        d["predictions"] = current if first_round else {name: previous[name] for name in names}
        d["current_predictions"] = current
        return d

    def collect_discuss(d, attrs):
        current_round = attrs["current_iteration"]
        last_votes = {name: reply["judgement"] for name, reply in d["predictions"].items()}
        votes = Counter(last_votes.values())
        unanimous = len(votes) == 1
        done = unanimous or current_round >= MAX_ROUNDS
        tied = sum(count == max(votes.values()) for count in votes.values()) > 1
        d.update(unanimous=unanimous, done=done, rounds=current_round, last_votes=last_votes,
                 prediction=votes.most_common(1)[0][0] if done else "",
                 decision_reason=("consensus" if unanimous else "tie_by_agent_order" if tied else "majority") if done else "")
        print(f"  第{current_round}轮：{dict(votes)}，重新判断={list(d['current_predictions'])}，结束={done}")
        return d

    def update_context(d, attrs):
        if d["unanimous"]:
            return d
        current_round = attrs["current_iteration"]

        def summarize(name):
            prompt = {
                "instruction": SUMMARY_INSTRUCTION.format(name=name), "claim": d["claim"],
                "previous conversation": d["histories"][name],
                # 作者这里只传本轮重新判断的 Agent，不是所有人的最新判断。
                "current round judgments": d["current_predictions"],
            }
            summary = summarizers[name].step({"prompt": prompt})["text"]
            return name, [{"name": name, "task": "", "message": summary, "round": current_round}]

        # 第十轮仍不一致也生成摘要；无人被说服时也用空的 current_predictions 生成摘要。
        with ThreadPoolExecutor(max_workers=AGENT_WORKERS) as pool:
            d["histories"] = dict(pool.map(summarize, names))
        return d

    steps = [("communicate", communicate), ("judge", judge),
             ("collect", collect_discuss), ("update_context", update_context)]

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

    graph = RootGraph(
        name="G1-P2-I4-C2-simple", nodes=[("discussion", discussion)],
        edges=[("entry", "discussion", fields), ("discussion", "exit", result_fields)],
    )
    graph.build()
    return graph, input_data


# 4. Read data -> run one graph per claim -> save results.
def main():
    global AGENT_WORKERS, INVOKE_ATTEMPTS, AUTHOR_ERRORS, PARSE_STRICT
    parser = argparse.ArgumentParser(description="G1-P2-I4-C2 claim verification")
    parser.add_argument("--data", type=Path, required=True, help="Processed JSON keyed by claim ID")
    parser.add_argument("--limit", type=int, default=0, help="First N selected claims; 0 means all")
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based offset in dataset order")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "results/G1-P2-I4-C2")
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
    output_path = args.resume or args.output_dir / f"mas_G1-P2-I4-C2_{timestamp}.json"
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
        results[claim_id] = {'judgement': out['prediction'], 'correct_answer': sample['labels'], 'rounds': out['rounds'], 'correct': out['prediction'] == sample['labels'], 'input_tokens': model.input_tokens, 'output_tokens': model.output_tokens, 'last_votes': out['last_votes'], 'decision_reason': out['decision_reason']}
        results[claim_id]["run_settings"] = {
            "strategy": "G1-P2-I4-C2", "model": args.model,
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
