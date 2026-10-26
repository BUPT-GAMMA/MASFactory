"""Compare local author and MASFactory predictions without model requests."""
import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


LABELS = ("supporting", "neutral", "refuting")


def load_json(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def normalize_label(label):
    # 兼容 Refuting**、**neutral** 等输出；只清理首尾格式，不从解释或错误文本中猜标签。
    return label.strip().strip("*").strip().lower()


# 2. 同一组样本上，统计准确率、token用量和轮数。
def summarize(results, ids, data):
    rows = [results[claim_id] for claim_id in ids]
    n = len(ids)
    correct = sum(normalize_label(results[k]["judgement"]) == data[k]["labels"] for k in ids)
    invalid = [k for k in ids if normalize_label(results[k]["judgement"]) not in LABELS]
    input_tokens = sum(row["input_tokens"] for row in rows)
    output_tokens = sum(row["output_tokens"] for row in rows)
    return {
        "samples": n,
        "correct": correct,
        "accuracy_percent": 100 * correct / n if n else None,
        "invalid_predictions": len(invalid),
        "invalid_ids": invalid,
        "prediction_counts": dict(Counter(normalize_label(row["judgement"]) for row in rows)),
        # 保留未规范化的统计，便于检查这次格式兼容的影响。
        "raw_accuracy_percent": 100 * sum(results[k]["judgement"] == data[k]["labels"] for k in ids) / n if n else None,
        "raw_invalid_predictions": sum(row["judgement"] not in LABELS for row in rows),
        "total_input_tokens": input_tokens,
        "total_output_tokens": output_tokens,
        "average_input_tokens": input_tokens / n if n else None,
        "average_output_tokens": output_tokens / n if n else None,
        "average_rounds": sum(row["rounds"] for row in rows) / n if n else None,
        "samples_reaching_round_10": sum(row["rounds"] == 10 for row in rows),
    }


def save_summary_table(path, summary):
    """用Python自带csv生成Excel可打开的表格，无需安装额外依赖。"""
    a, m = summary["author"], summary["masfactory"]
    rows = [["指标", "作者版", "MASFactory版", "差值（MAS-作者）", "说明"]]
    for title, key in [
        ("比较样本数", "samples"), ("正确数量", "correct"),
        ("准确率（%）", "accuracy_percent"), ("非法预测数量", "invalid_predictions"),
        ("原始字符串匹配准确率（%）", "raw_accuracy_percent"),
        ("原始字符串非法预测数量", "raw_invalid_predictions"),
        ("输入tokens总数", "total_input_tokens"), ("输出tokens总数", "total_output_tokens"),
        ("每样本平均输入tokens", "average_input_tokens"),
        ("每样本平均输出tokens", "average_output_tokens"),
        ("每样本平均讨论轮数", "average_rounds"),
        ("达到第10轮的样本数", "samples_reaching_round_10"),
    ]:
        note = "差值单位为百分点" if key in ("accuracy_percent", "raw_accuracy_percent") else ""
        rows.append([title, a[key], m[key], m[key] - a[key], note])
    for label in LABELS:
        av, mv = a["prediction_counts"].get(label, 0), m["prediction_counts"].get(label, 0)
        rows.append([f"预测为{label}的数量", av, mv, mv - av, ""])
    rows.extend([
        ["结果文件记录数", summary["author_records"], summary["masfactory_records"], "", ""],
        ["缺失样本数", len(summary["author_missing_ids"]), len(summary["masfactory_missing_ids"]), "", ""],
        [],
        ["两版共同统计", "数值", "", "", ""],
        ["数据集样本数", summary["dataset_samples"], "", "", ""],
        ["预测一致率（%）", summary["prediction_agreement_percent"], "", "", ""],
        ["预测不同的样本数", summary["different_predictions"], "", "", ""],
        ["两版均覆盖全量", "是" if summary["both_cover_full_dataset"] else "否", "", "", ""],
        [],
        ["作者结果文件", summary["author_file"], "", "", ""],
        ["MASFactory结果文件", summary["masfactory_file"], "", "", ""],
        ["统计说明", summary["note"], "", "", ""],
    ])
    # utf-8-sig带BOM，Windows Excel直接打开时中文不会乱码。
    try:
        file = path.open("w", encoding="utf-8-sig", newline="")
    except PermissionError:
        # Excel/WPS 打开表格时可能锁定文件；改存新文件，不强制关闭用户的表格。
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = path.with_name(f"{path.stem}_{timestamp}{path.suffix}")
        file = path.open("w", encoding="utf-8-sig", newline="")
        print(f"原CSV无法覆盖（可能被占用或只读），已另存为：{path}")
    with file:
        writer = csv.writer(file)
        for row in rows:
            writer.writerow([round(v, 4) if isinstance(v, float) else v for v in row])
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--author", type=Path, required=True)
    parser.add_argument("--mas", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    DATA_PATH, AUTHOR_PATH, MAS_PATH = args.data, args.author, args.mas
    # Do not allow generated reports to replace an input file.
    inputs = {p.resolve() for p in (DATA_PATH, AUTHOR_PATH, MAS_PATH)}
    for filename in ("summary.json", "all_samples.json", "different_predictions.json", "summary.csv"):
        if (args.output_dir / filename).resolve() in inputs:
            parser.error("Output files must not overwrite comparison inputs")
    author = load_json(AUTHOR_PATH)
    mas = load_json(MAS_PATH)
    data = load_json(DATA_PATH)

    # 3. 先核对ID和正确标签；不能拿不同样本的分数直接比较。
    for results in (author, mas):
        for claim_id, row in results.items():
            if claim_id not in data or row["correct_answer"] != data[claim_id]["labels"]:
                raise ValueError(f"样本ID或正确标签与数据集不一致：{claim_id}")
    common_ids = [k for k in data if k in author and k in mas]
    if not common_ids:
        raise ValueError("两份结果没有共同样本")

    # 4. 逐样本比较。所有对照保存一份，预测不同的另外保存一份。
    comparisons = []
    for claim_id in common_ids:
        a, m = author[claim_id], mas[claim_id]
        comparisons.append({
            "claim_id": claim_id,
            "gold": data[claim_id]["labels"],
            "agent_count": len(data[claim_id]["sentences_and_labels"]),
            "same_prediction": normalize_label(a["judgement"]) == normalize_label(m["judgement"]),
            "author_normalized_prediction": normalize_label(a["judgement"]),
            "masfactory_normalized_prediction": normalize_label(m["judgement"]),
            "author": a,
            "masfactory": m,
            "input_token_difference_mas_minus_author": m["input_tokens"] - a["input_tokens"],
            "output_token_difference_mas_minus_author": m["output_tokens"] - a["output_tokens"],
            "round_difference_mas_minus_author": m["rounds"] - a["rounds"],
        })
    differences = [row for row in comparisons if not row["same_prediction"]]
    agreement = 100 * (len(common_ids) - len(differences)) / len(common_ids)
    a_stats = summarize(author, common_ids, data)
    m_stats = summarize(mas, common_ids, data)
    summary = {
        "author_file": str(AUTHOR_PATH), "masfactory_file": str(MAS_PATH),
        "dataset_samples": len(data),
        "author_records": len(author), "masfactory_records": len(mas),
        "author_missing_ids": [k for k in data if k not in author],
        "masfactory_missing_ids": [k for k in data if k not in mas],
        "both_cover_full_dataset": set(author) == set(mas) == set(data),
        "comparison_samples": len(common_ids),
        "prediction_agreement_percent": agreement,
        "different_predictions": len(differences),
        "author": a_stats, "masfactory": m_stats,
        "accuracy_difference_percentage_points": m_stats["accuracy_percent"] - a_stats["accuracy_percent"],
        "note": "两版统一去掉标签首尾空白、Markdown星号并转小写，再精确匹配；不从解释或错误文本中提取标签。空标签和其他非法预测仍计为错误。原始预测保留，raw统计使用原始字符串。tokens为两版保存的文本计数，非账单。最终标签合法不能证明中间无API失败。第10轮也可能刚好达成一致。",
    }

    # 5. 结果按两份输入的名字分别归档；重复比较同一对文件会更新本对比目录。
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in [("summary.json", summary), ("all_samples.json", comparisons),
                          ("different_predictions.json", differences)]:
        with (output_dir / name).open("w", encoding="utf-8") as file:
            json.dump(content, file, ensure_ascii=False, indent=2)

    table_path = save_summary_table(output_dir / "summary.csv", summary)

    print(f"数据集{len(data)}条；作者{len(author)}条；MASFactory {len(mas)}条；共同{len(common_ids)}条")
    print(f"两版均覆盖全量：{summary['both_cover_full_dataset']}")
    print(f"{'指标':<20} {'作者':>14} {'MASFactory':>14}")
    for title, key in [("正确数量", "correct"), ("准确率(%)", "accuracy_percent"),
                       ("非法预测数量", "invalid_predictions"),
                       ("平均输入tokens", "average_input_tokens"),
                       ("平均输出tokens", "average_output_tokens"),
                       ("平均讨论轮数", "average_rounds"),
                       ("达到10轮的样本数", "samples_reaching_round_10")]:
        print(f"{title:<20} {a_stats[key]:>14.2f} {m_stats[key]:>14.2f}")
    print(f"预测一致率：{agreement:.2f}%；预测不同：{len(differences)}条")
    print(f"结果已保存：{output_dir}")
    print(f"对比表格：{table_path}")
