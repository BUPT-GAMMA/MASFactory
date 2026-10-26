"""G1-P1-I2-C2: MASFactory implementation of the author workflow."""
import argparse
import json
import os
import re
import tiktoken
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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
# C2 的摘要请求与发言请求共用这个模型，因此两类调用的tokens都会计入。
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


# 2. 图内使用 dict，模型使用作者的文本格式；这两个类只负责转换。
class AuthorFormatter(MessageFormatter):
    """发言提示词：与作者 predict_with_agent 的字典结构一致。"""

    def __init__(self, sentence_key):
        super().__init__()
        self.sentence_key = sentence_key
        self._is_input_formatter = self._is_output_formatter = True
        self._agent_introducer = OUTPUT_REQUIREMENTS

    def dump(self, message):
        if isinstance(message, str):
            return message  # system 消息保持为空。
        return str({
            "instruction": INSTRUCTION,
            "claim": message["claim"],
            "evidence": message[self.sentence_key],
            # I2+C2：自己的上一轮摘要，加上本轮排在自己前面的 Agent 发言。
            "previous conversation information": message["history"],
            "Output requirements": OUTPUT_REQUIREMENTS,
        })

    def format(self, message):
        result = re.search(r"Result:\s*(.*)", message)
        explanation = re.search(r"Explanation:\s*(.*)", message)
        prediction = ((result.group(1).strip() if result else "") or message).lower()
        # 保留一个检查，避免把错误文本当成答案投票；异常直接停止脚本。
        if prediction not in ("supporting", "neutral", "refuting"):
            raise ValueError(f"无法解析模型的判断：{message}")
        return {"prediction": prediction,
                "explanation": explanation.group(1).strip() if explanation else ""}


class SummaryFormatter(MessageFormatter):
    """摘要提示词：与作者 Agent.generate_history 一致，用 json.dumps(indent=2) 序列化。

    作者对发言用 str(dict)、对摘要用 json.dumps，两种序列化不能混用。
    """

    def __init__(self, agent_name):
        super().__init__()
        self.agent_name = agent_name
        self._is_input_formatter = self._is_output_formatter = True
        # 摘要没有输出格式要求；dump 会忽略这个字段，但基类要求非空。
        self._agent_introducer = "Return only the summary text."

    def dump(self, message):
        if isinstance(message, str):
            return message
        prompt = {
            "instruction": SUMMARY_INSTRUCTION.format(name=self.agent_name),
            "claim": message["claim"],
            "previous conversation": message["history"],
            "current round judgments": message["judgements"],
        }
        # 作者用默认的 ensure_ascii=True，这里保持同样写法。
        return json.dumps(prompt, indent=2)

    def format(self, message):
        # 作者把摘要原文直接当作 history 的 message，不做解析和清洗。
        return {"summary": message}


def terminate_cond(message, attrs):
    return message["done"]


# 3. 为一个样本建图：controller → sequential_agents → collect → update_context → controller。
def build_graph(sample, model):
    sentence_count = len(sample["sentences_and_labels"])
    # 每个 Agent 维护自己的摘要history，初始为空列表（与作者的 agent.history=[] 一致）。
    input_data = {
        "claim": sample["claim"],
        "histories": {f"Agent{i}": [] for i in range(1, sentence_count + 1)},
        "done": False,
    }
    agents, summarizers = [], []
    for i in range(1, sentence_count + 1):
        sentence_key = f"sentence{i}"
        input_data[sentence_key] = sample["sentences_and_labels"][i - 1]["sentence"]
        agent = Agent(
            name=f"Agent{i}", model=model, instructions="", prompt_template="",
            formatters=AuthorFormatter(sentence_key), hide_unused_fields=False,
            memories=[], pull_keys={}, push_keys={}, max_retries=1,
        )
        agent.build()
        agents.append(agent)
        # 摘要也由同一个Agent身份（Agent{i}）自己完成，所以每个Agent配一个摘要器。
        summarizer = Agent(
            name=f"Agent{i}-summary", model=model, instructions="", prompt_template="",
            formatters=SummaryFormatter(f"Agent{i}"), hide_unused_fields=False,
            memories=[], pull_keys={}, push_keys={}, max_retries=1,
        )
        summarizer.build()
        summarizers.append(summarizer)

    def sequential_agents(d, attrs):
        current_round = attrs["current_iteration"]
        histories = {name: list(history) for name, history in d["histories"].items()}
        replies = {}
        for i, agent in enumerate(agents, start=1):
            name = f"Agent{i}"
            reply = agent.step({
                "claim": d["claim"], f"sentence{i}": d[f"sentence{i}"],
                "history": histories[name],
            })
            replies[name] = reply
            # 对齐作者 add_history_last_round：说完立即广播，后面的 Agent 能看到。
            message = {"judgement": reply["prediction"], "explanation": reply["explanation"]}
            for other_name in histories:
                histories[other_name].append({"name": name, "message": message,
                                               "round": current_round})
                histories[other_name] = [entry for entry in histories[other_name]
                                         if entry["round"] >= current_round - 1]
        # 摘要环节必须拿到加入本轮发言后的 history，不能用 controller 的旧 history。
        return {"replies": replies, "histories": histories}

    def collect_discuss(d, attrs):
        current_round = attrs["current_iteration"]
        replies = d["replies"]
        last_votes = {name: reply["prediction"] for name, reply in replies.items()}
        votes = Counter(last_votes.values())
        unanimous = len(votes) == 1
        done = unanimous or current_round >= MAX_ROUNDS
        prediction = votes.most_common(1)[0][0] if done else ""
        tied = sum(count == max(votes.values()) for count in votes.values()) > 1
        decision_reason = ("consensus" if unanimous else
                           "tie_by_agent_order" if tied else "majority") if done else ""
        print(f"  第{current_round}轮：{dict(votes)}，结束={done}")
        # 作者把本轮所有Agent的判断和理由交给摘要环节，I2 的键顺序就是 Agent 编号顺序。
        judgements = {name: {"judgement": reply["prediction"],
                             "explanation": reply["explanation"]}
                      for name, reply in replies.items()}
        return {"judgements": judgements, "unanimous": unanimous, "done": done,
                "prediction": prediction, "rounds": current_round,
                "last_votes": last_votes, "decision_reason": decision_reason}

    def update_context(d, attrs):
        # C2：不一致时每个Agent用自己的summary替换history；一致时不生成摘要。
        current_round = attrs["current_iteration"]
        histories = {name: list(history) for name, history in d["histories"].items()}
        # 即使第十轮done=True，只要仍不一致，作者也会生成摘要；这部分tokens照常计入。
        if not d["unanimous"]:
            print(f"  第{current_round}轮：正在为{sentence_count}个Agent分别生成摘要")
            def summarize(index):
                name = f"Agent{index}"
                summary = summarizers[index - 1].step({
                    "claim": d["claim"], "history": histories[name],
                    "judgements": d["judgements"],
                })["summary"]
                # 作者的 update_history 会清空旧history，只留这一条摘要；
                # 字段顺序 name/task/message/round 会原样进入下一轮的提示词。
                return name, [{"name": name, "task": "", "message": summary,
                               "round": current_round}]

            with ThreadPoolExecutor(max_workers=AGENT_WORKERS) as pool:
                for name, history in pool.map(summarize, range(1, sentence_count + 1)):
                    histories[name] = history
        return {"histories": histories, "done": d["done"], "prediction": d["prediction"],
                "rounds": d["rounds"], "last_votes": d["last_votes"],
                "decision_reason": d["decision_reason"]}

    nodes = [
        ("sequential_agents", NodeTemplate(
            CustomNode, forward=sequential_agents,
            pull_keys={"current_iteration": "当前轮数"}, push_keys={},
        )),
        ("collect", NodeTemplate(
            CustomNode, forward=collect_discuss,
            pull_keys={"current_iteration": "当前轮数"}, push_keys={},
        )),
        ("update_context", NodeTemplate(
            CustomNode, forward=update_context,
            pull_keys={"current_iteration": "当前轮数"}, push_keys={},
        )),
    ]
    edges = [
        ("controller", "sequential_agents", {key: "" for key in input_data if key != "done"}),
        ("sequential_agents", "collect", {"replies": ""}),
        ("collect", "update_context", {
            "judgements": "", "unanimous": "", "done": "", "prediction": "",
            "rounds": "", "last_votes": "", "decision_reason": "",
        }),
        ("controller", "update_context", {"claim": ""}),
        ("sequential_agents", "update_context", {"histories": ""}),
        ("update_context", "controller", {
            "histories": "", "done": "", "prediction": "", "rounds": "",
            "last_votes": "", "decision_reason": "",
        }),
    ]

    discussion = NodeTemplate(
        Loop, max_iterations=MAX_ROUNDS, terminate_condition_function=terminate_cond,
        nodes=nodes, edges=edges,
    )
    graph = RootGraph(
        name="G1-P1-I2-C2-simple",
        nodes=[("discussion", discussion)],
        edges=[("entry", "discussion", {key: "" for key in input_data}),
               ("discussion", "exit", {"prediction": "", "rounds": "",
                                       "last_votes": "", "decision_reason": ""})],
    )
    graph.build()
    return graph, input_data


# 4. Read data -> run one graph per claim -> save results.
def main():
    global AGENT_WORKERS, INVOKE_ATTEMPTS, AUTHOR_ERRORS, PARSE_STRICT
    parser = argparse.ArgumentParser(description="G1-P1-I2-C2 claim verification")
    parser.add_argument("--data", type=Path, required=True, help="Processed JSON keyed by claim ID")
    parser.add_argument("--limit", type=int, default=0, help="First N selected claims; 0 means all")
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based offset in dataset order")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "results/G1-P1-I2-C2")
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
    output_path = args.resume or args.output_dir / f"mas_G1-P1-I2-C2_{timestamp}.json"
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
            "strategy": "G1-P1-I2-C2", "model": args.model,
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
