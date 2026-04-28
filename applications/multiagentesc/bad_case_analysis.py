"""
Bad Case 分析脚本
分析方向：
1. 策略预测错误（pred_strategy vs GT）
2. 路径选择错误（zero-shot vs 复杂路径）
3. 响应质量（逐样本 BLEU/ROUGE）
4. None 预测的根因（is_complex判断、response差异）
"""
import json, os, re
from collections import Counter

import nltk
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt", quiet=True)

from nltk.util import ngrams as _ngrams
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
from rouge_score import rouge_scorer

# ============ 加载数据 ============

with open("dataset/ESConv.json") as f:
    dataset = json.load(f)

with open("results.json") as f:
    results = json.load(f)

# 提取 GT strategies（与 workflow 对齐的顺序）
def load_gt_strategies(n_samples):
    gt_strats = []
    count = 0
    for sample in dataset:
        dialog = sample["dialog"]
        c = 0
        while c < len(dialog):
            if c != 0 and dialog[c]["speaker"] == "supporter":
                is_single = (c < len(dialog) - 1 and dialog[c + 1]["speaker"] != "supporter") or (c == len(dialog) - 1)
                gt_strats.append(dialog[c]["annotation"]["strategy"])
                count += 1
                c += 1 if is_single else 2
                if count >= n_samples:
                    break
            else:
                c += 1
        if count >= n_samples:
            break
    return gt_strats

gt_strategies = load_gt_strategies(len(results))
assert len(gt_strategies) == len(results), f"{len(gt_strategies)} vs {len(results)}"

# ============ 清理 response ============

def clean_response(resp):
    if not resp or resp == "None":
        return ""
    if "Reasoning:" in resp:
        resp = resp.split("Reasoning:")[0].strip()
    for prefix in ["Refined response:", "refined response:",
                   "Original response:", "original response:"]:
        if resp.startswith(prefix):
            resp = resp[len(prefix):].strip()
    return resp.strip()

# ============ 逐样本指标 ============

scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
smooth = SmoothingFunction().method1

samples = []
for i, (r, gt_strat) in enumerate(zip(results, gt_strategies)):
    pred = clean_response(r.get("response", ""))
    ref = r.get("reference", "")
    pred_strat = r.get("pred_strategy", "None")
    has_complex_path = "emotion" in r  # 有 emotion 字段说明走了复杂路径

    # BLEU
    if pred and ref:
        b1 = sentence_bleu([ref.split()], pred.split(), weights=(1, 0, 0), smoothing_function=smooth) * 100
        b2 = sentence_bleu([ref.split()], pred.split(), weights=(0.5, 0.5, 0, 0), smoothing_function=smooth) * 100
        rl = scorer.score(ref, pred)["rougeL"].fmeasure * 100
    else:
        b1 = b2 = rl = 0.0

    samples.append({
        "idx": i,
        "strategy_match": pred_strat == gt_strat,
        "strategy": gt_strat,
        "pred_strategy": pred_strat,
        "zero_shot": pred_strat == "None",
        "complex_path": has_complex_path,
        "b1": b1,
        "b2": b2,
        "rouge_l": rl,
        "pred": pred[:80],
        "ref": ref[:80],
        "response_len": len(pred.split()),
        "reference_len": len(ref.split()),
    })

# ============ 分析维度 ============

print("=" * 80)
print("1. 整体统计")
print("=" * 80)
total = len(samples)
strat_correct = sum(1 for s in samples if s["strategy_match"])
zero_shot = sum(1 for s in samples if s["zero_shot"])
complex_path = sum(1 for s in samples if s["complex_path"])

print(f"总样本: {total}")
print(f"策略正确: {strat_correct}/{total} ({strat_correct/total*100:.1f}%)")
print(f"走 zero-shot (pred=None): {zero_shot}/{total} ({zero_shot/total*100:.1f}%)")
print(f"走复杂路径: {complex_path}/{total} ({complex_path/total*100:.1f}%)")

print(f"\n平均 BLEU-1: {sum(s['b1'] for s in samples)/total:.2f}")
print(f"平均 BLEU-2: {sum(s['b2'] for s in samples)/total:.2f}")
print(f"平均 ROUGE-L: {sum(s['rouge_l'] for s in samples)/total:.2f}")

# ============

print("\n" + "=" * 80)
print("2. Zero-shot 路径分析（pred_strategy=None）")
print("=" * 80)
# Zero-shot 样本的 GT 策略分布
zero_shot_samples = [s for s in samples if s["zero_shot"]]
zero_shot_strats = Counter(s["strategy"] for s in zero_shot_samples)
print("GT策略分布（被误判为zero-shot的）:")
for s, c in zero_shot_strats.most_common():
    print(f"  {s:<40} {c}")

# Zero-shot 样本 vs 非 zero-shot 的 BLEU
zs_b1 = sum(s["b1"] for s in zero_shot_samples) / max(len(zero_shot_samples), 1)
non_zs = [s for s in samples if not s["zero_shot"]]
non_zs_b1 = sum(s["b1"] for s in non_zs) / max(len(non_zs), 1)
print(f"\nZero-shot 路径平均 BLEU-1: {zs_b1:.2f}")
print(f"复杂路径平均 BLEU-1: {non_zs_b1:.2f}")

# ============

print("\n" + "=" * 80)
print("3. 策略预测错误分析")
print("=" * 80)
wrong = [s for s in samples if not s["strategy_match"] and not s["zero_shot"]]
print(f"复杂路径但策略错误: {len(wrong)} 条")

# 错误类型分类
from collections import defaultdict
error_types = defaultdict(list)
for s in wrong:
    gt = s["strategy"]
    pred = s["pred_strategy"]
    # 单策略 vs 组合策略
    if " and " in gt and " and " not in pred:
        error_types["GT=组合, pred=单"].append(s)
    elif " and " not in gt and " and " in pred:
        error_types["GT=单, pred=组合"].append(s)
    elif " and " in gt and " and " in pred:
        error_types["组合 vs 组合（部分匹配）"].append(s)
    else:
        error_types[f"单 vs 单: {gt}→{pred}"].append(s)

for etype, cases in sorted(error_types.items(), key=lambda x: -len(x[1])):
    print(f"\n  {etype}: {len(cases)} 条")

# ============

print("\n" + "=" * 80)
print("4. BLEU 最低的 Bad Cases（Top 10）")
print("=" * 80)
worst_b1 = sorted(samples, key=lambda x: x["b1"])[:15]
print(f"{'idx':<4} {'B-1':>6} {'R-L':>6} {'GT策略':<35} {'Pred':<25}")
print("-" * 100)
for s in worst_b1:
    print(f"{s['idx']:<4} {s['b1']:>6.2f} {s['rouge_l']:>6.2f} {s['strategy']:<35} {s['pred_strategy']:<25}")

# ============

print("\n" + "=" * 80)
print("5. ROUGE-L 最低的 Bad Cases（Top 10）")
print("=" * 80)
worst_rl = sorted(samples, key=lambda x: x["rouge_l"])[:10]
print(f"{'idx':<4} {'B-1':>6} {'R-L':>6} {'GT策略':<35} {'Pred策略':<25}")
print("-" * 100)
for s in worst_rl:
    print(f"{s['idx']:<4} {s['b1']:>6.2f} {s['rouge_l']:>6.2f} {s['strategy']:<35} {s['pred_strategy']:<25}")

# ============

print("\n" + "=" * 80)
print("6. 策略粒度对比（GT单策略样本）")
print("=" * 80)
single_gt = [s for s in samples if " and " not in s["strategy"]]
single_match = sum(1 for s in single_gt if s["strategy_match"])
print(f"GT单策略样本: {len(single_gt)}, 预测正确: {single_match} ({single_match/len(single_gt)*100:.1f}%)")

combo_gt = [s for s in samples if " and " in s["strategy"]]
combo_match = sum(1 for s in combo_gt if s["strategy_match"])
print(f"GT组合策略样本: {len(combo_gt)}, 预测正确: {combo_match} ({combo_match/len(combo_gt)*100:.1f}%)")

# ============

print("\n" + "=" * 80)
print("7. 典型 Bad Case 详情（随机选5个zero-shot误判 + 5个策略错误）")
print("=" * 80)

# zero-shot 误判详情
print("\n--- Zero-shot 误判（走简单路径但GT非None）---")
zs_wrong = [s for s in samples if s["zero_shot"] and s["strategy"] != "None"][:5]
for s in zs_wrong:
    r = results[s["idx"]]
    print(f"\n[样本 {s['idx']}]")
    print(f"  GT策略: {s['strategy']}")
    print(f"  参考回复: {r.get('reference','')[:120]}")
    print(f"  生成回复: {s['pred'][:120]}")
    print(f"  BLEU-1: {s['b1']:.2f}  ROUGE-L: {s['rouge_l']:.2f}")

# 策略错误详情
print("\n--- 策略预测错误（复杂路径）---")
wrong_detail = wrong[:5]
for s in wrong_detail:
    r = results[s["idx"]]
    print(f"\n[样本 {s['idx']}]")
    print(f"  GT策略: {s['strategy']}")
    print(f"  预测策略: {s['pred_strategy']}")
    if s.get("emotion"):
        print(f"  情绪: {s.get('emotion','')}")
    print(f"  参考回复: {r.get('reference','')[:120]}")
    print(f"  生成回复: {s['pred'][:120]}")
    print(f"  BLEU-1: {s['b1']:.2f}  ROUGE-L: {s['rouge_l']:.2f}")

# ============

print("\n" + "=" * 80)
print("8. 响应长度对比")
print("=" * 80)
avg_pred_len = sum(s["response_len"] for s in samples) / total
avg_ref_len = sum(s["reference_len"] for s in samples) / total
print(f"生成回复平均词数: {avg_pred_len:.1f}")
print(f"参考回复平均词数: {avg_ref_len:.1f}")
print(f"长度比 (pred/ref): {avg_pred_len/max(avg_ref_len,1):.2f}")

# 长度与BLEU的关系
longer = [s for s in samples if s["response_len"] > s["reference_len"] * 1.5]
shorter = [s for s in samples if s["response_len"] < s["reference_len"] * 0.5]
print(f"\n过长回复(>1.5x): {len(longer)} 条, 平均B-1: {sum(s['b1'] for s in longer)/max(len(longer),1):.2f}")
print(f"过短回复(<0.5x): {len(shorter)} 条, 平均B-1: {sum(s['b1'] for s in shorter)/max(len(shorter),1):.2f}")
