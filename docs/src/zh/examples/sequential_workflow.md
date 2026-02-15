# 串行工作流

本示例展示如何构建一个简单的顺序执行工作流，多个节点按照依赖关系依次执行。

## 消息传递视角

- **水平（Edge keys）**：`user_question -> requirements_report -> codes`
- **垂直（attributes）**：本示例未使用，可在需要共享状态时增加（参考 `/zh/examples/attributes`）

## 示意图
![示意图](/imgs/examples/sequential_workflow.png)
## 示意代码（声明式，推荐）

```python
from masfactory import Agent, OpenAIModel, RootGraph, NodeTemplate

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

BaseAgent = NodeTemplate(Agent, model=model)

graph = RootGraph(
    name="demo",
    nodes=[
        ("analyser", BaseAgent(instructions="你是产品经理，负责做需求分析。", prompt_template="用户需求：{user_question}")),
        ("coder", BaseAgent(instructions="你是资深程序员，根据需求分析写代码。", prompt_template="需求分析：{requirements_report}")),
    ],
    edges=[
        ("entry", "analyser", {"user_question": "用户需求"}),
        ("analyser", "coder", {"requirements_report": "需求分析报告"}),
        ("coder", "exit", {"codes": "生成的代码"}),
    ],
)

graph.build()
out, _attrs = graph.invoke({"user_question": "写一个两数相加的 Python 函数"})
print(out["codes"])
```

::: tip 提示
`RootGraph.invoke(...)` 返回 `(output_dict, attributes_dict)`。
:::

## 示意代码（命令式，备选）

```python
from masfactory import Agent, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

graph = RootGraph(name="demo")

analyser = graph.create_node(
    Agent,
    name="analyser",
    model=model,
    instructions="你是产品经理，负责做需求分析。",
    prompt_template="用户需求：{user_question}",
)
coder = graph.create_node(
    Agent,
    name="coder",
    model=model,
    instructions="你是资深程序员，根据需求分析写代码。",
    prompt_template="需求分析：{requirements_report}",
)

graph.edge_from_entry(analyser, {"user_question": "用户需求"})
graph.create_edge(analyser, coder, {"requirements_report": "需求分析报告"})
graph.edge_to_exit(coder, {"codes": "生成的代码"})

graph.build()
out, _attrs = graph.invoke({"user_question": "写一个两数相加的 Python 函数"})
print(out["codes"])
```
