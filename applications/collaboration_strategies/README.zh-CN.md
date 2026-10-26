# 使用 MASFactory 复现多智能体协作策略

[English](README.md)

本应用实现论文 **Beyond Frameworks: Unpacking Collaboration Strategies in
Multi-Agent Systems**（Wang 等，ACL 2025）中的九种协作策略。

- [论文](https://aclanthology.org/2025.acl-long.1037/)
- [作者代码](https://github.com/s65b40/collaboration_MAS)
- [AmbiFC 数据集](https://github.com/CambridgeNLIP/verification-real-world-info-needs)

范围是 AmbiFC 的声明验证，不包含 MIMIC-III 实验。下文两版都使用 `gpt-4o-mini`，
比较的是这个模型设置下作者基线与 MASFactory 实现的表现，不是精确复现论文原模型的分数。

## 目录

```text
collaboration_strategies/
├── README.md
├── README.zh-CN.md
├── .gitignore
├── prepare_data.py
├── compare_results.py
├── merge_results.py
└── workflows/
    ├── g1_p1_i1_c1.py
    ├── g1_p1_i1_c2.py
    ├── g1_p1_i2_c1.py
    ├── g1_p1_i2_c2.py
    ├── g1_p1_i3_c1.py
    ├── g1_p1_i3_c2.py
    ├── g1_p2_i4_c2.py
    ├── g2_p3_i1_c3.py
    └── g2_p3_i2_c3.py
```

每个策略保留独立脚本：提示词、Formatter、建图函数和运行循环都在同一个文件中，
便于对照阅读。不附带数据集、结果 JSON、临时测试代码、AI 交互记录或作者仓库副本。
补跑中必要的参数和合并操作已整理进正式入口，不需要导入本地 `rerun` 目录。

## 流程设计

每条样本创建一个 `RootGraph`，使用 `Loop` 管理最多十轮讨论。图中的阶段是
`CustomNode`，在阶段函数内部调用各角色的 `Agent.step()`，不是每个 Agent 都单独占一个图节点。

| 策略家族 | 每轮流程 |
|---|---|
| G1-P1 | 发言 → 汇总判断 → 按策略更新历史或摘要 |
| G1-P2-I4-C2 | 选择对象并说服 → 重新判断 → 汇总 → 更新摘要 |
| G2-P3 | 发言 → Instructor 决策 → 摘要和下一轮选人 |

- I1：同轮并行判断，看不到本轮其他人刚生成的回答。
- I2：按 Agent 编号依次发言，后发言者能看到前面新增的信息。
- I3：每轮随机排列发言顺序。
- I4：各 Agent 自己选择说服对象；第一轮之后，只有**收到说服消息**的人重新判断，
  不意味着一定被成功说服或改变意见。
- C1：维护近期对话记录；C2：各 Agent 单独生成自己的摘要；C3：Instructor 生成摘要。

G1 全员一致时提前结束，十轮仍不一致时取最高票，平票按各策略的顺序规则处理。
G2 的结论由 Instructor 给出，不添加多数票兜底。G2 未形成结论时可能返回空标签、
`rounds=0`，实际执行轮数另外记录在 `actual_rounds`。

## 环境准备

在 MASFactory 仓库根目录安装本地框架：

```bash
python -m pip install -e .
```

本地离线检查使用 MASFactory 1.0.4；集成到其他版本时仍需检查兼容性。

PowerShell 配置：

```powershell
$env:OPENAI_API_KEY = "<你的 API key>"
$env:OPENAI_BASE_URL = "<你的 API 基础地址>"
```

Bash 配置：

```bash
export OPENAI_API_KEY="<你的 API key>"
export OPENAI_BASE_URL="<你的 API 基础地址>"
```

基础地址是兼容 OpenAI 客户端的 API 根地址，不要填完整的 `/chat/completions` 请求地址。
密钥不写进代码文件。

## 数据准备

从 AmbiFC 上游下载数据，找到 `test.certain.jsonl`。另行下载作者仓库：

```bash
git clone https://github.com/s65b40/collaboration_MAS.git ../collaboration_MAS
python applications/collaboration_strategies/prepare_data.py --author-code ../collaboration_MAS --input /path/to/test.certain.jsonl --output /path/to/filtered_test_certain_new.json
```

工具读取作者 `fact_code/filter_claim_data.py` 中的函数，不执行其主入口，依次调用两个阶段：

1. 保留句内标注一致的句子，保留句子标签存在分歧的样本。
2. 排除空句子，把标签与 passage 标签相同的证据排在前面，再从其他证据补足，最多六句。

第二阶段即使不足六句也会重排分组，因此顺序讨论时必须保留这个处理方式。
本次处理后共有 501 条：409 条 supporting、92 条 refuting，每条有 1～6 个 Agent。
模型仍然允许预测 supporting、neutral、refuting 三类。真值用于作者的数据清洗和评估，
不放入模型推理提示词。产物是按 claim ID 索引的 JSON 字典，不是 JSONL。

输出文件已存在时工具会报错，请换一个文件名。只有准备数据需要作者 checkout，
运行九个 MAS 工作流不依赖作者仓库。

## 运行与续跑

以下命令都在 MASFactory 仓库根目录执行。`/path/to/...` 要换成自己的路径，包含空格时加引号。

先跑一条：

```bash
python -B -X utf8 applications/collaboration_strategies/workflows/g1_p1_i1_c1.py --data /path/to/filtered_test_certain_new.json --limit 1 --output-dir /path/to/results
```

全量将 `--limit 1` 改成 `--limit 0`，其他策略替换脚本名即可。每完成一条样本就保存，
先写临时文件再替换结果文件。新运行使用带时间戳的文件名。不同样本按 for 循环依次运行，
线程池用于策略内部允许并行的阶段。

断点续跑：

```bash
python -B -X utf8 applications/collaboration_strategies/workflows/g1_p1_i1_c1.py --data /path/to/filtered_test_certain_new.json --limit 0 --resume /path/to/previous_result.json
```

续跑会跳过**所有已保存的 ID**，包括已保存的无效或空标签。
默认 `--on-error stop` 在异常时停止，失败样本不保存，下次从该样本第一轮重新开始。
`--on-error record` 则把异常记为空标签和错误原因后继续；它不是自动补跑错误样本。
不按预测是否正确决定保留哪条结果。续跑时应保持策略、数据和模型配置一致，
不要让两个进程同时写同一个结果文件。

| 参数 | 含义与默认值 |
|---|---|
| `--data` | 必填，清洗后的数据文件 |
| `--limit` | 选择区间的前 N 条，0 为全部 |
| `--start-index` | 从数据中第几个位置开始，按 0 起算，默认 0；之后才应用 limit |
| `--output-dir` | 默认放在应用目录的 `results/<策略>/` |
| `--resume` | 指定已有结果文件；不指定则新建 |
| `--model` | 默认 gpt-4o-mini |
| `--timeout` | 默认 60 秒 |
| `--sdk-retries` | 保留旧脚本的 1000000 次有限重试上限 |
| `--invoke-attempts` | MASFactory adapter 每次调用最多尝试数，含首次，默认 3 |
| `--agent-workers` | 线程池并发数，默认 Python 的默认值；只影响并行阶段 |
| `--on-error` | stop 或 record，默认 stop |

重试分为三层：OpenAI SDK、MASFactory 模型 adapter、Agent 执行/格式解析。
只设置 `--sdk-retries 0` 不会关闭 adapter 重试；同时设 `--invoke-attempts 1` 才会关闭前两层的额外尝试。
Agent 层保留旧实现：除 G2-P3-I2-C3 的判断 Agent 最多尝试 3 次外，其余为 1 次，
该 G2 版本的 Instructor 仍是 1 次。SDK 默认上限很大，接口异常时可能等待很久，
可以明确指定较小的值。

## I2-C1、I3-C1 补跑方式

这两份脚本额外提供两个独立参数：

- `--loose-parse`：不因判断不是三类标签而报错，保留原回复作为一票。
- `--author-errors`：模型调用耗尽尝试仍失败时，转换为作者固定的错误文本。
  它本身不会关闭重试，也不会关闭标签检查。

I2-C1 补跑采用的请求和解析设置：

```bash
python -B -X utf8 applications/collaboration_strategies/workflows/g1_p1_i2_c1.py --data /path/to/filtered_test_certain_new.json --limit 0 --timeout 180 --sdk-retries 0 --invoke-attempts 3 --loose-parse --author-errors --output-dir /path/to/i2_rerun
```

历史 I2 启动器在图执行异常时跳过该样本、不保存；整理版默认停止，排查后可续跑，
正常讨论逻辑不变。历史 I2 adapter 实际仍保留重试，因此不能写成“请求失败处理与作者完全一致”。

I3-C1 尾段补跑采用的设置（第 321～501 条）：

```bash
python -B -X utf8 applications/collaboration_strategies/workflows/g1_p1_i3_c1.py --data /path/to/filtered_test_certain_new.json --start-index 320 --limit 0 --sdk-retries 0 --invoke-attempts 1 --loose-parse --on-error record --output-dir /path/to/i3_tail
```

这里保留了原尾段脚本的区别：格式异常的回复可以进入投票，请求异常则中止该样本并记为空结果。
重试次数是已记录的实验条件变化，不能说已经证明它导致了之前的分数变化。
I3 的发言顺序随机，不保证再次运行得到相同输出。

新结果每条记录附带不含密钥的 `run_settings`。后面的分数是整理前的历史实验，
不能描述成整理版在统一配置下重新跑出的结果。

## 合并与比较

合并互不重叠的分片，重复 ID 会报错：

```bash
python applications/collaboration_strategies/merge_results.py --data /path/to/filtered_test_certain_new.json --inputs /path/to/shard0.json /path/to/shard1.json --output /path/to/merged.json
```

按数据顺序组合旧文件前段与补跑后段，作者和 MAS 分别执行一次：

```bash
python applications/collaboration_strategies/merge_results.py --data /path/to/filtered_test_certain_new.json --head /path/to/earlier.json --tail /path/to/tail.json --split-index 320 --output /path/to/combined.json
```

合并只按分片归属或数据位置取记录，不按预测对错选择。前后段组合要求覆盖全量；
普通分片合并不足全量时明确提示。两种模式都不覆盖已有文件。

结果对比：

```bash
python applications/collaboration_strategies/compare_results.py --data /path/to/filtered_test_certain_new.json --author /path/to/author.json --mas /path/to/mas.json --output-dir /path/to/comparison
```

比较脚本校验 ID 和真值，按共同 ID 计算，报告缺失 ID，输出 `summary.json`、`summary.csv`、
`all_samples.json`、`different_predictions.json`。同一输出目录再次运行会更新报告。
统一清理标签大小写、首尾空白和 Markdown 星号后精确匹配，无效/空标签算错，不从解释中猜答案。
覆盖不完整不能当成全量成绩。数据准备、合并和比较工具不调用模型 API。

## 历史实验结果

每行均为 501 条配对记录，分数及一致率单位为百分比，差值为 MAS 减作者的百分点数。
这些是观察结果，不是统计等价性的证明。

| 策略 | 作者准确率 | MAS 准确率 | 差值 | 一致率 |
|---|---:|---:|---:|---:|
| G1-P1-I1-C1 | 18.56 | 17.37 | -1.20 | 89.02 |
| G1-P1-I1-C2 | 65.67 | 67.27 | +1.60 | 88.02 |
| G1-P1-I2-C1 | 75.05 | 73.05 | -2.00 | 85.43 |
| G1-P1-I2-C2 | 65.07 | 65.47 | +0.40 | 85.03 |
| G1-P1-I3-C1 | 36.33 | 36.73 | +0.40 | 81.24 |
| G1-P1-I3-C2 | 74.65 | 68.46 | -6.19 | 82.44 |
| G1-P2-I4-C2 | 83.23 | 87.62 | +4.39 | 89.82 |
| G2-P3-I1-C3 | 89.02 | 88.62 | -0.40 | 92.02 |
| G2-P3-I2-C3 | 84.23 | 90.02 | +5.79 | 87.23 |

### 来源与限制

- I2-C1 两版各八个分片，最终合并文件时间戳为 `20261025_150412`。全量启动器曾接入较早
  小批量中已完成的 100 条，再补剩余样本，不能说全部 501 条都在一次全新连续运行中完成。
- I3-C1 由两版旧结果各自前 320 条，加后续补跑各自后 181 条组成，合并时间戳同为
  `20261025_150412`。过程中换过 key 或接口/渠道，不是一个环境始终不变的单次实验。
- 其他结果的作者/MAS 文件时间戳分别为：I1-C1 `20261019_225822` / `20261020_162919`；
  I1-C2 `20261020_165540` / `20261021_111517`；I2-C2 `20261021_174650` / `20261021_175053`；
  I3-C2 `20261022_105248` / `20261022_105856`；I4-C2 `20261022_155656` / `20261022_232629`；
  G2-I1-C3 `20261022_232230` / `20261022_232728`；G2-I2-C3 `20261022_232348` / `20261022_232735`。
  对应本地 `author_<策略>_<时间戳>.json` 和 `mas_<策略>_<时间戳>.json`，原始产物未随应用分发。
- 分母保留无效标签：I1-C2 作者 13 条；I3-C1 MAS 9 条；G2-I2-C3 作者 3 条、MAS 2 条。
- G2 作者基线修正了调用错误：`update_history` 的 message 传摘要、current_round 传整数；
  G2-I2 的顺序发言函数补传 current_round。两版采用同样的修正语义，基线不是完全未修改的公开版。
- 作者 API 可能把错误文本当作正常回答；MAS 默认检查判断标签并抛错，历史运行重试也存在差异。
  最终标签合法不代表中间请求全部成功。
- tokens 是 `tiktoken` 对 user 提示词正文和回复的计数，包含摘要、Instructor 等调用，
  不是服务商账单。SDK 内部失败、未保存或覆盖掉的尝试可能没有计入；保存了失败样本也不保证
  其计数覆盖所有请求消耗。
- G2 即使实际讨论过多轮，未决策时仍可能记 rounds=0。一致率比较的是规范化后的文本是否相同，
  不表示两边相同的回答一定是有效标签。

## 引用

```bibtex
@inproceedings{wang-etal-2025-beyond,
    title = "Beyond Frameworks: Unpacking Collaboration Strategies in Multi-Agent Systems",
    author = "Wang, Haochun and Zhao, Sendong and Wang, Jingbo and Qiang, Zewen and Qin, Bing and Liu, Ting",
    booktitle = "Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)",
    year = "2025",
    publisher = "Association for Computational Linguistics",
    pages = "21361--21375",
    url = "https://aclanthology.org/2025.acl-long.1037/",
    doi = "10.18653/v1/2025.acl-long.1037"
}
```
