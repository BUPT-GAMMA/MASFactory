"""DMAD_MAS entry point.

Loads a dataset (ScienceQA / mm-vet), runs multi-agent debate via DMAD_GRAPH,
and saves results.
"""
import os
import json
import argparse

from Dataset import read_dataset
from graph import make_graph
from record import extract_answer

parser = argparse.ArgumentParser()
parser.add_argument("--dataset", type=str, default="ScienceQA")
parser.add_argument("--num_items", type=int, default=-1, help="limit number of items, -1 = all")
args = parser.parse_args()

DATASET_NAME = args.dataset
SPLIT = "test" if DATASET_NAME == "ScienceQA" else ""
ANSWER_DIR = os.path.join("answer", DATASET_NAME)
RESULTS_FILE = os.path.join(ANSWER_DIR, f"{DATASET_NAME}{'_' + SPLIT if SPLIT else ''}_DMAD_results.json")
IO_FILE      = os.path.join(ANSWER_DIR, f"{DATASET_NAME}-io.json")
CCOT_FILE    = os.path.join(ANSWER_DIR, f"{DATASET_NAME}-ccot.json")
DDCOT_FILE   = os.path.join(ANSWER_DIR, f"{DATASET_NAME}-ddcot.json")

IS_MMVET = (DATASET_NAME == "mm-vet")


def _load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


print(f"Loading {DATASET_NAME}...")
raw_data = read_dataset(DATASET_NAME, SPLIT)

if IS_MMVET:
    keys = sorted(raw_data.keys(), key=lambda k: int(k.split("_")[1]))
    dataset = {k: raw_data[k] for k in keys}
    if args.num_items > 0:
        keys = keys[:args.num_items]
        dataset = {k: raw_data[k] for k in keys}
    all_total = len(dataset)
else:
    dataset = [d for d in raw_data if d["image"] is not None]
    if args.num_items > 0:
        dataset = dataset[:args.num_items]
    all_total = len(dataset)

print(f"Total items: {all_total}")

results = _load_json(RESULTS_FILE)
io_answers   = _load_json(IO_FILE)
ccot_answers = _load_json(CCOT_FILE)
ddcot_answers = _load_json(DDCOT_FILE)

start = len(results)
total = min(start + 1, all_total)

if start > 0:
    print(f"Resuming from index {start} ({start}/{all_total} already done)")

graph = make_graph(DATASET_NAME)
print("Building graph...")
graph.build()
print("Graph built successfully.")

for i in range(start, total):
    if IS_MMVET:
        item_id = keys[i]
        item = dataset[item_id]
        question_text = item["question"]
        image_path = os.path.join("dataset/mm-vet/images", item["imagename"])
    else:
        item = dataset[i]
        question_text = item["question"]
        image_path = f"dataset/ScienceQA/{i}.png"

    print(f"\n[{i+1}/{all_total}] {question_text[:80]}...")
    print(f"  image: {image_path}")

    output, attrs = graph.invoke({
        "question":   item,
        "image_path": image_path,
    })

    results.append({
        "index":         i,
        "question_text": question_text,
        "ground_truth":  item.get("answer") if not IS_MMVET else None,
        "all_answers":   output.get("all_answers", []),
    })

    all_ans = output.get("all_answers", [["", "", ""], ["", "", ""], ["", "", ""]])
    entry = {
        "index":        i,
        "question":     question_text,
        "ground_truth": item.get("answer") if not IS_MMVET else None,
    }

    io_answers.append({**entry, "answers": [
        all_ans[0][0], all_ans[1][0], all_ans[2][0],
    ], "extracted": [
        extract_answer(all_ans[0][0]), extract_answer(all_ans[1][0]), extract_answer(all_ans[2][0]),
    ]})
    ccot_answers.append({**entry, "answers": [
        all_ans[0][1], all_ans[1][1], all_ans[2][1],
    ], "extracted": [
        extract_answer(all_ans[0][1]), extract_answer(all_ans[1][1]), extract_answer(all_ans[2][1]),
    ]})
    ddcot_answers.append({**entry, "answers": [
        all_ans[0][2], all_ans[1][2], all_ans[2][2],
    ], "extracted": [
        extract_answer(all_ans[0][2]), extract_answer(all_ans[1][2]), extract_answer(all_ans[2][2]),
    ]})

    _save_json(RESULTS_FILE, results)
    _save_json(IO_FILE,      io_answers)
    _save_json(CCOT_FILE,    ccot_answers)
    _save_json(DDCOT_FILE,   ddcot_answers)

    print(f"  saved to {ANSWER_DIR}/ ({len(results)}/{all_total})")

print(f"\nDone. Results saved to {ANSWER_DIR}/")

if not IS_MMVET:
    from record import calculate_consistency_acc
    print("\n=== Evaluation ===")
    calculate_consistency_acc(dataset=DATASET_NAME, reasoning="DMAD", split=SPLIT)
else:
    print("\nmm-vet: skip built-in evaluation (use external judge)")
