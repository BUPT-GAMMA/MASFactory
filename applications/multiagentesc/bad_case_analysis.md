# Bad Case 分析报告

> 数据: results.json (54 条样本, dataset[:3])
> 模型: qwen2.5-32b-instruct (DashScope)

## 整体统计

| 指标 | 数值 |
|------|------|
| 总样本 | 54 |
| 策略预测正确 | 6/54 (11.1%) |
| 走 zero-shot 路径 | 18/54 (33.3%) |
| 走复杂路径 | 36/54 (66.7%) |
| 平均 BLEU-1 | 8.33 |
| 平均 ROUGE-L | 10.75 |
| 生成回复平均词数 | 19.9 |
| 参考回复平均词数 | 20.3 |

## 核心问题（按影响排序）

### 1. Zero-shot 误判（18/54 = 33%）

最严重的问题。`is_complex` 把 18 个本该走复杂路径的对话判为"不复杂"，直接 zero-shot 生成，策略无法预测。

被误判为 zero-shot 的 GT 策略分布：

| GT 策略 | 数量 |
|---------|------|
| Question | 7 |
| Affirmation and Reassurance | 2 |
| Others | 2 |
| Information | 2 |
| Self-disclosure | 2 |
| Restatement or Paraphrasing | 2 |
| Providing Suggestions | 1 |

Zero-shot 路径平均 BLEU-1 (8.17) vs 复杂路径平均 BLEU-1 (8.41)，差距不大，说明 zero-shot 生成的响应质量本身还可以，但策略信息完全丢失。

**典型案例：**
- 样本 1: GT=Question ("What makes your job stressful for you?"), 生成=共情式回复, BLEU-1=4.55
- 样本 3: GT=Affirmation and Reassurance, 生成=共情式回复, BLEU-1=5.99

### 2. 策略过预测为组合策略（13/30）

走了复杂路径但策略预测错误的 30 条中，有 13 条 GT 是单策略但被预测为组合策略（如 "Affirmation and Reassurance and Reflection of feelings"）。

这说明策略讨论阶段的 3 个 agent 倾向于输出多个策略，投票/裁判环节没有有效收敛到单策略。

### 3. Reflection of feelings 泛滥

单策略错误中，有 5 条被错误预测为 `Reflection of feelings`，是所有错误预测中出现最多的目标策略。模型对这个策略有明显偏好。

### 4. BLEU=0 的极端 Bad Case

4 条样本 BLEU-1=0（idx 15, 16, 21, 36），生成内容与参考完全无重叠：

| idx | GT策略 | Pred策略 | 参考回复 | 生成回复 |
|-----|--------|---------|---------|---------|
| 15 | Question | AR | "Is this a significant other?" | "It's really tough feeling disconnected..." |
| 16 | Question | AR | "Are they ignoring you?" | "It sounds really tough to feel left out..." |
| 21 | AR | AR | "..." | "..." |
| 36 | Others | Question | "..." | "..." |

样本 15/16 最为典型：GT 要求一个简短的提问（Question），但模型生成了一长段共情（Affirmation and Reassurance），方向完全错误。

## 策略粒度对比

| 粒度 | 样本数 | 预测正确 | 准确率 |
|------|--------|---------|--------|
| GT 单策略 | 44 | 3 | 6.8% |
| GT 组合策略 | 10 | 3 | 30.0% |

## 响应长度分析

| 类型 | 数量 | 平均 BLEU-1 |
|------|------|------------|
| 过长回复 (>1.5x ref) | 18 | 5.82 |
| 过短回复 (<0.5x ref) | 3 | 4.86 |
| 长度正常 | 33 | ~9.5 |

## 结论

1. **主要瓶颈是 is_complex 判断**：33% 的样本被错误分流到 zero-shot，导致策略信息完全丢失。这比策略预测不准的影响更大。
2. **策略讨论收敛性差**：复杂路径中 30/36 条策略预测错误，agent 倾向于输出多个策略而非收敛到正确策略。
3. **模型偏好共情类策略**：Reflection of feelings 和 Affirmation and Reassurance 被过度预测，Question 等需要精确提问的策略被忽视。
4. **生成质量本身可接受**：BLEU-1=8.33 vs 源码基线 BLEU-1=10.29，差距主要来自策略错误导致的方向偏差，而非语言质量问题。
