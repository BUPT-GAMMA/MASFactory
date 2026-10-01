# MaAS Reproduction — 基于 MASFactory 的 MaAS 复现

本项目使用 [MASFactory](https://github.com/BUPT-GAMMA/MASFactory) 原生图组件复现论文 **Multi-agent Architecture Search via Agentic Supernet (MaAS)**。系统针对每个问题，由可训练的 Controller 选择多智能体算子路径，并在执行后依据任务得分与模型调用成本更新策略。

当前支持 `GSM8K`、`MATH` 和 `HumanEval`，包含训练、断点续训、加载训练权重测试。

## 论文与上游项目

- 论文：[Multi-agent Architecture Search via Agentic Supernet](https://arxiv.org/abs/2502.04180)
- 原始 MaAS 实现：[github.com/bingreeky/MaAS](https://github.com/bingreeky/MaAS)
- 多智能体框架：[BUPT-GAMMA/MASFactory](https://github.com/BUPT-GAMMA/MASFactory)

## 项目结构

```text
maas_reproduction/
├── main.py                         # 统一命令行入口
├── workflow.py                     # 训练图与测试图的 RootGraph 定义
├── components/                     # 路由、算子、评估和结果节点
├── maas_reproduction/
│   ├── adapters/                   # 数据、成本、产物和代码执行适配器
│   ├── benchmarks/                 # GSM8K、MATH、HumanEval 评分器
│   ├── models/                     # Controller、嵌入模型和模型工厂
│   ├── runtime/                    # 配置、运行循环、日志和 checkpoint
│   ├── source_compat/              # 原始 MaAS 行为兼容层
│   └── training/                   # 训练信号与批量梯度累积
├── assets/
│   ├── config/                     # 实验、模型、算子和评估配置
│   ├── data/                       # 本地 JSONL 数据集（需自行准备）
│   ├── prompts/                    # 各数据集使用的提示词
│   └── output/                     # 运行结果、日志与 checkpoint
└── environment.yml                 # 可直接创建的 Conda 运行环境
```

> 本项目按 MASFactory 的 application 目录结构编写。最终目录必须是 `<MASFactory>/applications/maas_reproduction/`，并且所有下文命令都要在 `<MASFactory>` 仓库根目录执行。直接在本目录运行 `python main.py` 会破坏 Python 包上下文，不能作为启动方式。

## 环境准备

### 1. 放置项目

先获取 MASFactory：

```powershell
git clone https://github.com/BUPT-GAMMA/MASFactory.git MASFactory-main
```

如果拿到的是独立的 `maas_reproduction` 文件夹，请将整个文件夹复制到：

```text
MASFactory-main/applications/maas_reproduction
```

如果该目录已经包含在你的 MASFactory 副本中，则无需再次复制。

### 2. 创建环境并安装 MASFactory

```bash
conda env create -f environment.yml
conda activate mas_env
cd MASFactory-main
pip install -e . --no-deps
```

验证包路径：

```powershell
python -c "import masfactory; import applications.maas_reproduction; print('environment ready')"
```

## 模型与密钥配置

创建 `.env`：

```dotenv
OPENAI_API_KEY=your_api_key_here
BASE_URL=https://your-openai-compatible-endpoint/v1
```

- `OPENAI_API_KEY` 是当前 `assets/config/models.json` 通过 `api_key_env` 指定的必填变量。
- `BASE_URL` 是可选变量；使用官方 OpenAI 地址时可以留空或删除。

模型本身在 `assets/config/models.json` 中配置：

```json
{
  "provider": "deepseek",
  "model_name": "gpt-4o-mini",
  "api_key_env": "OPENAI_API_KEY",
  "base_url_env": "BASE_URL",
  "temperature": 0.0,
  "max_tokens": 16384,
  "input_cost_per_1k_tokens": 0.00015,
  "output_cost_per_1k_tokens": 0.0006
}
```

请让 `provider`、`model_name`、`BASE_URL` 和密钥与实际服务保持一致：

- `provider: "openai"` 使用 MASFactory 的 OpenAI Responses API 适配器。
- `provider: "deepseek"` 使用兼容 Chat Completions 的适配器，也可连接提供该协议的网关。
- 训练依赖可靠的调用成本。

## 数据准备

数据不会自动下载。请将数据放到：

```text
applications/maas_reproduction/assets/data/
├── gsm8k_train.jsonl
├── gsm8k_test.jsonl
├── math_train.jsonl
├── math_test.jsonl
├── humaneval_train.jsonl
├── humaneval_test.jsonl
└── humaneval_public_test.jsonl      # 运行 HumanEval 时额外需要
```

## 配置实验

日常实验主要修改 `assets/config/experiments.json`：

| 字段 | 含义 | 当前默认值 |
| --- | --- | --- |
| `dataset` | `GSM8K`、`MATH` 或 `HumanEval` | `GSM8K` |
| `split` | `train` 或 `test` | `test` |
| `mode` | `train` 或 `test` | `test` |
| `sample` | 单次调用最多处理的样本数 | `2` |
| `batch_size` | Controller 梯度更新批量 | `4` |
| `epochs` | 训练轮数 | `1` |
| `seed` | 随机种子 | `42` |
| `learning_rate` | Controller 学习率 | `0.001` |
| `output_root` | 运行产物根目录 | `assets/output` |

## 运行训练

正式跑完整数据集时按需要设置 epoch：

```powershell
python -m applications.maas_reproduction.main --mode train --dataset GSM8K --split train --epochs 3 --fresh
```

训练行为说明：

- 不传 `--fresh` 和 `--resume` 时，程序会自动寻找 `assets/output/run_*/checkpoints/latest.pt` 中最新的 checkpoint 并续训。
- `--fresh` 始终新建运行；它不能与 `--resume` 同时使用。
- `--resume <checkpoint>` 从指定 checkpoint 恢复 Controller、优化器、数据游标和随机状态。
- `--sample N` 只限制本次调用处理 N 条数据，下次调用可自动续跑。

显式恢复示例：

```powershell
python -m applications.maas_reproduction.main --mode train --dataset GSM8K --split train --epochs 3 --resume applications/maas_reproduction/assets/output/run_YYYYMMDD_HHMMSS_xxxxxx/checkpoints/latest.pt
```

测试不会自动寻找训练 checkpoint；需要通过 `--resume` 明确指定。测试只加载 Controller 权重，也不会把测试结果写入原训练目录。

### 支持的主入口参数

| 参数 | 说明 |
| --- | --- |
| `--mode {train,test}` | 运行模式 |
| `--dataset {GSM8K,MATH,HumanEval}` | 数据集 |
| `--split {train,test}` | 数据切分 |
| `--sample N` | 本次调用最多处理 N 条样本 |
| `--epochs N` | 覆盖配置中的 epoch 数 |
| `--fresh` | 新建训练运行，不自动恢复 |
| `--resume PATH` | 加载本项目 checkpoint |
| `--source-bundle PATH` | 测试原始 MaAS Controller bundle |

## 输出文件

每次新运行会在 `applications/maas_reproduction/assets/output/` 下创建独立目录：

```text
assets/output/run_YYYYMMDD_HHMMSS_xxxxxx/
├── config.json                       # 本次运行实际使用的关键配置
├── metrics.json                      # 样本数、成功/失败数、均分、均成本等
├── results/
│   └── sample_<problem_index>.json   # 每个样本的公开结果
├── logs/
│   ├── run.log                       # JSON Lines 运行事件
│   └── error.log                     # 启动或执行错误
└── checkpoints/                      # 训练模式下生成
    ├── latest.pt                     # 最近一个可恢复的批边界
    └── checkpoint_epoch_<N>.pt       # 每个完整 epoch 的历史 checkpoint
```

MATH 和 HumanEval 使用相同的产物结构：

| **File** | **Description** |
| --- | --- |
| `config.json` | 本次运行实际采用的数据集、切分、模型和训练参数 |
| `metrics.json` | 总样本数、成功/失败数、总体准确率、平均成本和更新次数 |
| `results/sample_<problem_index>.json` | 单道题的预测、得分、所选算子、成本与执行状态 |
| `logs/run.log` | JSON Lines 格式的逐样本、逐 epoch 运行记录 |
| `logs/error.log` | 启动、模型调用、图执行或保存阶段的错误记录 |
| `checkpoints/latest.pt` | 最近一个可安全恢复的训练 checkpoint |
| `checkpoints/checkpoint_epoch_<N>.pt` | 每个完整 epoch 对应的历史 checkpoint |

## Results

以下结果将本项目复现结果与原始 MaAS 仓库报告的结果进行对照。

### MATH — Overall Accuracy

| **Result** | **Our Accuracy** | **Original Accuracy** |
| --- | ---: | ---: |
| Overall | 51.23% | 51.28% |

### HumanEval — Overall Accuracy

| **Result** | **Our Accuracy** | **Original Accuracy** |
| --- | ---: | ---: |
| Overall | 90.93% | 92.85% |
