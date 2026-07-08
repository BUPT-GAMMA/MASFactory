"""Evaluation utilities: answer extraction, majority voting, accuracy calculation,
and mm-vet evaluation format conversion with GPT-based answer selection."""
import json
import os
import random
import re
from collections import Counter


def _load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_answer(output=None, dataset="ScienceQA"):
    """Extract answer letter A-G from model output text."""
    assert output is not None
    if isinstance(output, list):
        output = output[0]
    try:
        if dataset == "ScienceQA":
            a = re.search(r"he answer is (.)", output)
            if a is not None:
                option = a.group(1)
                if option < "A" or option > "G":
                    pattern = r"\(([A-G])\)"
                    match = re.search(pattern, output)
                    if match is None:
                        option = re.search(r"\*\*(.)", output).group(1)
                    else:
                        option = match.group(1)
                        if option < "A" or option > "G":
                            option = re.search(r"\*\*(.)", output).group(1)
            else:
                a = re.search(r"correct option is (.)", output)
                if a is not None:
                    option = a.group(1)
                    if option < "A" or option > "G":
                        pattern = r"\(([A-G])\)"
                        match = re.search(pattern, output)
                        option = match.group(1)
                else:
                    a = re.search(r"correct answer is (.)", output)
                    if a is not None:
                        option = a.group(1)
                        if option < "A" or option > "G":
                            pattern = r"\(([A-G])\)"
                            match = re.search(pattern, output)
                            option = match.group(1)
                    else:
                        pattern = r"\(([A-G])\)"
                        match = re.search(pattern, output)
                        option = match.group(1)
    except Exception:
        option = None
    return option


def find_most_common_elements(input_list):
    """Return the most frequent elements and their count."""
    input_list = [x for x in input_list if x is not None]
    if len(input_list) == 0:
        return [None], 0
    counter = Counter(input_list)
    max_count = max(counter.values())
    most_common = [element for element, count in counter.items() if count == max_count]
    return most_common, max_count


def calculate_consistency_acc(dataset="ScienceQA", reasoning="DMAD",
                               split="test", num=3, agents=3, rounds=3):
    """Compute DMAD debate accuracy for ScienceQA.

    Reads from ScienceQA_test_DMAD_results.json. Each round performs
    majority voting across the 3 agents and compares with ground_truth.
    Results are saved to {dataset}-DMAD-Accuracy.json.
    """
    random.seed(0)
    answer_dir = os.path.join("answer", dataset)
    result_file = os.path.join(answer_dir, f"{dataset}-DMAD-Accuracy.json")
    filepath = os.path.join(answer_dir, f"{dataset}_{split}_DMAD_results.json")
    outputs = _load_json(filepath)
    if len(outputs) == 0:
        print(f"No data found at {filepath}")
        return

    right_num = [0] * rounds
    for output in outputs:
        true_answer = output["ground_truth"]
        for r in range(rounds):
            answers = [extract_answer(output["all_answers"][r][a]) for a in range(agents)]
            most_common, _ = find_most_common_elements(answers)
            answer = random.choice(most_common)
            if answer is not None and true_answer == ord(answer) - 65:
                right_num[r] += 1

    total = len(outputs)
    accuracy = {}
    for r in range(rounds):
        acc = right_num[r] / total
        accuracy[f"round_{r}"] = {"correct": right_num[r], "total": total, "accuracy": acc}
        print(f"Accuracy of round {r} DMAD on {dataset}: {right_num[r]} / {total} = {acc:.4f}")

    _save_json(result_file, {
        "dataset": dataset, "split": split,
        "agents": agents, "rounds": rounds, "total_items": total,
        "accuracy": accuracy,
    })
    print(f"Accuracy saved to {result_file}")


# --- GPT judge: select best answer from 3 candidates (for mm-vet DMAD) ---

_EVAL_PROMPT = """Compare the three answers to the question below and select the best one.

Question: {question}

Answer 1: {solution1}

Answer 2: {solution2}

Answer 3: {solution3}

Which answer is the best? Output a JSON object with "Reason" (explain why) and "Index" (1, 2, or 3).
Format: {{"Reason": "...", "Index": "1"}}"""


def _get_eval_client():
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv()
    return OpenAI(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
    )


def _eval_select_best(question, solution1, solution2, solution3):
    """Use GPT to pick the best answer from 3 candidates."""
    import random as _random
    client = _get_eval_client()
    prompt = _EVAL_PROMPT.format(
        question=question,
        solution1=solution1, solution2=solution2, solution3=solution3,
    )
    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=200,
        )
        content = response.choices[0].message.content
        index = re.search(r"ndex\":\s*\"(\d)\"", content)
        idx = index.group(1) if index else str(_random.choice(["1", "2", "3"]))
        if idx not in ("1", "2", "3"):
            idx = str(_random.choice(["1", "2", "3"]))
        return int(idx)
    except Exception:
        return _random.choice([1, 2, 3])


# --- mm-vet evaluation format conversion ---

def align_mmvet(dataset="mm-vet", reasoning="DMAD", agents=3, rounds=3):
    """Convert DMAD_MAS outputs to mm-vet official eval format {question_id: answer}.

    For DMAD, uses GPT to select the best answer from the 3 agents per round.
    """
    answer_dir = os.path.join("answer", dataset)
    mmvet_path = os.path.join(answer_dir, "mm-vet_eval")
    os.makedirs(mmvet_path, exist_ok=True)

    if reasoning in ("io", "ccot", "ddcot"):
        filepath = os.path.join(answer_dir, f"{dataset}-{reasoning}.json")
        outputs = _load_json(filepath)
        if len(outputs) == 0:
            print(f"No data at {filepath}")
            return
        logs = {}
        for i, item in enumerate(outputs):
            logs[f"v1_{i}"] = item["answers"][0]
        out_path = os.path.join(mmvet_path, f"{reasoning}.json")
        _save_json(out_path, logs)
        print(f"Saved {len(logs)} items to {out_path}")

    elif reasoning == "DMAD":
        filepath = os.path.join(answer_dir, f"{dataset}_DMAD_results.json")
        outputs = _load_json(filepath)
        if len(outputs) == 0:
            print(f"No data at {filepath}")
            return
        for r in range(rounds):
            logs = {}
            for i, item in enumerate(outputs):
                question = item.get("question_text", "")
                s1, s2, s3 = item["all_answers"][r]
                idx = _eval_select_best(question, s1, s2, s3)
                logs[f"v1_{i}"] = item["all_answers"][r][idx - 1]
            out_path = os.path.join(mmvet_path, f"DMAD_round_{r}.json")
            _save_json(out_path, logs)
            print(f"Saved round {r} ({len(logs)} items) to {out_path}")
