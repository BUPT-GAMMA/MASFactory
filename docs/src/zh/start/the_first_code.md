# 第一行代码（从 0 到 1）

本页目标：让你在几分钟内写出**能跑起来**的 MASFactory 工作流，并理解最关键的用法（`RootGraph / Node / Edge / build / invoke`）。

---

## 0) 先理解 2 个概念

1. **MASFactory 使用 Python 的 `dict` 作为消息载体**：输入、节点输出、边上转发的数据，统一用结构化 `dict` 表达，节点收发消息的最小单位是`dict`中的一个字段。
   - **水平消息传递（Horizontal）**：同一个 `Graph` 内部的节点通过 `Edge` 交换消息（payload）。`Edge.keys` 用于定义字段契约与转发规则，“这一跳要传哪些字段”由边决定。
   - **垂直消息传递（Vertical）**：节点与其所在的 `Graph` 之间通过 `attributes`（结点变量）共享/交换消息，并通过节点的 `pull_keys / push_keys` 决定从 attributes 读取/回写哪些字段。
   - 详细机制见：[消息传递](/zh/guide/message_passing)。
2. `RootGraph.invoke(...)` **返回二元组**：`(output_dict, attributes_dict)` 第一个元素对应“水平消息传递”的最终输出，第二个元素对应“垂直消息传递”的 attributes 快照。

### 示意图：水平（Edge）+ 垂直（attributes）
<ThemedDiagram light="/imgs/message/overview-light.svg" dark="/imgs/message/overview-dark.svg" alt="消息总览：水平传递（Edge）+ 垂直传递（attributes）" />

---

## 1) 第一个 Agent 工作流
在这里我们将构造一个简单的问答系统，它包含两个 Agent，一个用于分析问题，另一个用于回答问题。

### 示意图：analyze → answer
<ThemedDiagram
  light="/imgs/tutorial/first-agent-workflow-light.svg"
  dark="/imgs/tutorial/first-agent-workflow-dark.svg"
  alt="第一个 Agent 工作流：ENTRY → analyze → answer → EXIT"
/>

```python
from masfactory import RootGraph, Agent, OpenAIModel, NodeTemplate, HistoryMemory

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",        
    model_name="gpt-4o-mini",
)

history = HistoryMemory(top_k=12)
BaseAgent = NodeTemplate(Agent, model=model, memories=[history])

g = RootGraph(
    name="qa_two_stage",
    nodes=[
        ("analyze", BaseAgent(instructions="你是问题分析专家。", prompt_template="用户问题：{query}")),
        ("answer", BaseAgent(instructions="你是解决方案专家，基于分析给出最终回答。", prompt_template="问题：{query}\n分析：{analysis}")),
    ],
    edges=[
        ("entry", "analyze", {"query": "用户问题"}),
        ("analyze", "answer", {"query": "原始问题", "analysis": "分析结果"}),
        ("answer", "exit", {"answer": "最终回答"}),
    ],
)

g.build()
out, _attrs = g.invoke({"query": "我想学习 Python，但不知道从哪里开始"})
print(out["answer"])
```

::: tip 从环境变量读取模型配置
MASFactory 不会自动读取环境变量；但你可以在创建 `OpenAIModel` 时手动从环境变量取值：

```python
import os
from masfactory import OpenAIModel

model = OpenAIModel(
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL") or None,
    model_name=os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
)
```

:::

::: tip 为什么 Agent 读不到 attributes？
`Agent` 的 `pull_keys/push_keys` 默认值是 `{}`， 在此设定下，Agent 不会读取 attributes，也不会回写 attributes。  
如果你希望 Agent 直接读取图的 attributes，要显式设置 `pull_keys` 为所需字段，如果设置 `pull_keys=None` 则从图上获取所有 attributes。
:::

---

## 3) 下一步学什么？

- 想系统学习声明式编排：看「开发指南」和「示例」章节。
- 想直接跑大量可运行对比例子：运行仓库里的 `examples/run_all.py`（包含命令式 vs 声明式对照）。
