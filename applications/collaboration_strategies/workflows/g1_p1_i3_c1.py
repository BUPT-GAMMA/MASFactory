"""G1-P1-I3-C1: MASFactory implementation of the author workflow."""
import argparse
import json
import os
import re
import random
import tiktoken
from collections import Counter
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

# 与作者 predict_with_agent 一致：每个 Agent 每轮只调用一次模型，失败也照原文投票。
# 2026-10-24：续跑时曾改成 3，导致前 320 条与后 181 条不是同一套语义，现已改回 1。
AGENT_MAX_RETRIES = 1
# True：回复里没有合法标签就抛错（原行为，需要重试或人工介入）。
# False：把原文当标签投进票箱，与作者 predict_with_agent 完全一致。
PARSE_STRICT = True

# 与作者 predict_with_agent 中的提示词相同。
INSTRUCTION = "You are tasked with evaluating the truth of a given claim. You must base your judgment solely on available evidence and previous conversation information. Do not use any knowledge or information from your own model-based understanding or internal training data. Your judgment should rely entirely on the facts and evidence presented, and you should not infer beyond what is directly supported by those sources. "
OUTPUT_REQUIREMENTS = "Please strictly follow this format:\nResult: <Your answer from one of these three options: supporting, neutral, refuting>\nExplanation: <Brief explanation of why you made this choice>"


# 与作者一样，用tiktoken统计提示词正文和原始回复；不是服务商账单usage。
class CountedModel(LegacyOpenAIModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.encoder = tiktoken.encoding_for_model("gpt-4o")
        self.input_tokens = 0
        self.output_tokens = 0
        self.token_lock = Lock()

    def invoke(self, messages, tools=None, settings=None, **kwargs):
        kwargs.setdefault("max_retries", INVOKE_ATTEMPTS)
        try:
            response = super().invoke(messages, tools, settings, **kwargs)
        except Exception:
            if not AUTHOR_ERRORS:
                raise
            # Historical I2 reruns returned this text after request failures.
            response = {"content": "Error: Request failed due to a network issue."}
        # 本脚本最后一条消息是user提示词；content是尚未经过formatter解析的回复。
        input_count = len(self.encoder.encode(messages[-1]["content"]))
        output_count = len(self.encoder.encode(response["content"]))
        with self.token_lock:
            self.input_tokens += input_count
            self.output_tokens += output_count
        return response


# 2. 图内使用 dict，模型使用作者的文本格式；这个类只负责两者的转换。
class AuthorFormatter(MessageFormatter):
    def __init__(self, sentence_key, strict=True):
        super().__init__()
        self.sentence_key = sentence_key
        self.strict = strict
        self._is_input_formatter = self._is_output_formatter = True
        self._agent_introducer = OUTPUT_REQUIREMENTS

    def dump(self, message):
        if isinstance(message, str):
            return message  # system 消息保持为空。
        return str({
            "instruction": INSTRUCTION,
            "claim": message["claim"],
            "evidence": message[self.sentence_key],
            "previous conversation information": message["history"],
            "Output requirements": OUTPUT_REQUIREMENTS,
        })

    def format(self, message):
        result = re.search(r"Result:\s*(.*)", message)
        explanation = re.search(r"Explanation:\s*(.*)", message)
        prediction = ((result.group(1).strip() if result else "") or message).lower()
        # 作者的做法是不校验：拿不到合法标签就把整段原文当答案投票（必然判错，但会进 history）。
        # strict=True 只是复现实验时加的护栏，避免把错误文本默默当成一票。
        if self.strict and prediction not in ("supporting", "neutral", "refuting"):
            raise ValueError(f"无法解析模型的判断：{message}")
        return {"prediction": prediction,
                "explanation": explanation.group(1).strip() if explanation else ""}


def terminate_cond(message, attrs):
    return message["done"]


# 3. 为一个样本建图：controller → sequential_agents → collect → controller。
def build_graph(sample, model, max_retries=AGENT_MAX_RETRIES, parse_strict=PARSE_STRICT):
    sentence_count = len(sample["sentences_and_labels"])
    input_data = {"claim": sample["claim"], "history": [], "done": False}
    agents = []
    for i in range(1, sentence_count + 1):
        sentence_key = f"sentence{i}"
        input_data[sentence_key] = sample["sentences_and_labels"][i - 1]["sentence"]
        agent = Agent(
            name=f"Agent{i}", model=model, instructions="", prompt_template="",
            formatters=AuthorFormatter(sentence_key, strict=parse_strict),
            hide_unused_fields=False,
            memories=[], pull_keys={}, push_keys={}, max_retries=max_retries,
        )
        agent.build()
        agents.append(agent)

    def sequential_agents(d, attrs):
        current_round = attrs["current_iteration"]
        # C1 中所有 Agent 收到相同的广播，history 内容始终一致，共用一个列表即可。
        history = list(d["history"])
        replies = {}
        # 与作者 random.sample(agents, len(agents)) 一致：每轮重新排列全部 Agent。
        # 把原编号与 Agent 放在一起打乱，保证 Agent3 始终读取 sentence3。
        selected_agents = random.sample(list(enumerate(agents, start=1)), len(agents))
        print(f"  第{current_round}轮发言顺序：{[f'Agent{i}' for i, _ in selected_agents]}")
        for i, agent in selected_agents:
            name = f"Agent{i}"
            reply = agent.step({
                "claim": d["claim"], f"sentence{i}": d[f"sentence{i}"],
                "history": history,
            })
            replies[name] = reply
            # 对齐作者：每人说完立即加入 history，下一位能看到本轮前面的发言。
            history.append({
                "name": name,
                "message": {"judgement": reply["prediction"], "explanation": reply["explanation"]},
                "round": current_round,
            })
            # 必须在发言后清理：新一轮第一个发言者仍会看到前两轮历史，
            # 它说完后才删除更早一轮，其余 Agent 看到上一轮和本轮已有发言。
            history = [entry for entry in history if entry["round"] >= current_round - 1]
        return {"replies": replies, "history": history}

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
                           "tie_by_speaking_order" if tied else "majority") if done else ""
        print(f"  第{current_round}轮：{dict(votes)}，结束={done}")

        # history 已在顺序发言时更新；collect 只判断投票，不再次追加，不生成摘要。
        return {"history": d["history"], "done": done,
                "prediction": prediction, "rounds": current_round,
                "last_votes": last_votes, "decision_reason": decision_reason}

    nodes = [
        ("sequential_agents", NodeTemplate(
            CustomNode, forward=sequential_agents,
            pull_keys={"current_iteration": "当前轮数"}, push_keys={},
        )),
        ("collect", NodeTemplate(
            CustomNode, forward=collect_discuss,
            pull_keys={"current_iteration": "当前轮数"}, push_keys={},
        )),
    ]
    edges = [
        ("controller", "sequential_agents", {key: "" for key in input_data if key != "done"}),
        ("sequential_agents", "collect", {"replies": "", "history": ""}),
        ("collect", "controller", {"history": "", "done": "", "prediction": "", "rounds": "",
                                  "last_votes": "", "decision_reason": ""}),
    ]

    discussion = NodeTemplate(
        Loop, max_iterations=MAX_ROUNDS, terminate_condition_function=terminate_cond,
        nodes=nodes, edges=edges,
    )
    graph = RootGraph(
        name="G1-P1-I3-C1-simple",
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
    parser = argparse.ArgumentParser(description="G1-P1-I3-C1 claim verification")
    parser.add_argument("--data", type=Path, required=True, help="Processed JSON keyed by claim ID")
    parser.add_argument("--limit", type=int, default=0, help="First N selected claims; 0 means all")
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based offset in dataset order")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "results/G1-P1-I3-C1")
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
    parser.add_argument("--loose-parse", action="store_true", help="Keep non-label replies as votes")
    parser.add_argument("--author-errors", action="store_true", help="Return author-style error text on API failures")
    args = parser.parse_args()
    if args.limit < 0 or args.start_index < 0 or args.sdk_retries < 0 or args.invoke_attempts < 1 or args.timeout <= 0:
        parser.error("Limits/retries must be nonnegative; timeout and invoke-attempts must be positive")
    if args.agent_workers is not None and args.agent_workers < 1:
        parser.error("agent-workers must be positive")
    AGENT_WORKERS = args.agent_workers
    INVOKE_ATTEMPTS = args.invoke_attempts
    AUTHOR_ERRORS = args.author_errors
    PARSE_STRICT = not args.loose_parse
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
    output_path = args.resume or args.output_dir / f"mas_G1-P1-I3-C1_{timestamp}.json"
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
        graph, input_data = build_graph(sample, model, max_retries=1, parse_strict=PARSE_STRICT)
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
            "strategy": "G1-P1-I3-C1", "model": args.model,
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
