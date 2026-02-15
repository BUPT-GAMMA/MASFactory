# 自定义节点（CustomNode）

`CustomNode` 允许你用纯 Python 写节点逻辑（数据清洗、格式转换、打分、聚合等），并与 `Agent/Graph/Loop/Switch` 混合编排。

## 消息传递视角

- **水平（Edge keys）**：`entry -> analyzer -> stats -> exit`，并通过 join 聚合多条入边字段
- **垂直（attributes）**：可用于缓存中间状态或配置；本示例主要展示水平 join

## 示意图
![示意图](/imgs/examples/custom_node.png)

## 示例：Agent 做分析 + CustomNode 做统计

## 示例代码（声明式，推荐）

```python
from __future__ import annotations

import re

from masfactory import Agent, CustomNode, NodeTemplate, OpenAIModel, RootGraph


model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

BaseAgent = NodeTemplate(Agent, model=model)


def stats_node(d: dict) -> dict:
    text = str(d.get("text", ""))
    words = [w for w in re.split(r"\\s+", text.strip()) if w]
    return {
        "text_stats": {
            "word_count": len(words),
            "char_count": len(text),
            "sentence_count": len(re.findall(r"[.!?。！？]+", text)),
        },
        "analysis": {
            "topic": d.get("topic"),
            "sentiment": d.get("sentiment"),
            "keywords": d.get("keywords"),
            "summary": d.get("summary"),
        },
    }


g = RootGraph(
    name="text_analysis_with_customnode",
    nodes=[
        ("analyzer", BaseAgent(instructions="你是文本分析专家，输出主题、情感、关键词、摘要。", prompt_template="{text}")),
        ("stats", CustomNode, stats_node),
    ],
    edges=[
        # entry -> analyzer：提供 text
        ("entry", "analyzer", {"text": "待分析文本"}),
        # entry -> stats：stats 也需要原文（并行输入）
        ("entry", "stats", {"text": "原始文本"}),
        # analyzer -> stats：把分析字段发送到 stats（join）
        ("analyzer", "stats", {"topic": "主题", "sentiment": "情感", "keywords": "关键词", "summary": "摘要"}),
        # stats -> exit
        ("stats", "exit", {"text_stats": "统计信息", "analysis": "分析结果"}),
    ],
)

g.build()
out, _attrs = g.invoke({"text": "人工智能正在快速发展，它改变了我们的生活方式……"})
print(out["text_stats"])
print(out["analysis"])
```

## 示例代码（命令式，备选）

```python
from __future__ import annotations

import re

from masfactory import Agent, CustomNode, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)


def stats_node(d: dict) -> dict:
    text = str(d.get("text", ""))
    words = [w for w in re.split(r"\\s+", text.strip()) if w]
    return {
        "text_stats": {
            "word_count": len(words),
            "char_count": len(text),
            "sentence_count": len(re.findall(r"[.!?。！？]+", text)),
        },
        "analysis": {
            "topic": d.get("topic"),
            "sentiment": d.get("sentiment"),
            "keywords": d.get("keywords"),
            "summary": d.get("summary"),
        },
    }


g = RootGraph(name="text_analysis_with_customnode")

analyzer = g.create_node(
    Agent,
    name="analyzer",
    model=model,
    instructions="你是文本分析专家，输出主题、情感、关键词、摘要。",
    prompt_template="{text}",
)
stats = g.create_node(CustomNode, name="stats", forward=stats_node)

g.edge_from_entry(analyzer, {"text": "待分析文本"})
g.edge_from_entry(stats, {"text": "原始文本"})
g.create_edge(analyzer, stats, {"topic": "主题", "sentiment": "情感", "keywords": "关键词", "summary": "摘要"})
g.edge_to_exit(stats, {"text_stats": "统计信息", "analysis": "分析结果"})

g.build()
out, _attrs = g.invoke({"text": "人工智能正在快速发展，它改变了我们的生活方式……"})
print(out["text_stats"])
print(out["analysis"])
```
