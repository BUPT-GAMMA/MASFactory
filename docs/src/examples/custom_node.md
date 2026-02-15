# Custom Node Example

This example demonstrates how to create and use `CustomNode` in MASFactory, implementing specific business logic, data processing and tool integration.
We will create a simple workflow: Agent node for text analysis, CustomNode for data statistics.

## Message Passing View

- **Horizontal (Edge keys):** `entry -> analyzer -> processor -> exit`, with join-style multi-input aggregation
- **Vertical (attributes):** optional for caching config/intermediate state; this example is mostly horizontal

## Diagram
![Diagram](/imgs/examples/custom_node.png)

## Example Code

### Declarative (recommended)

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
        ("analyzer", BaseAgent(instructions="You are a text analyst. Output topic/sentiment/keywords/summary.", prompt_template="{text}")),
        ("stats", CustomNode, stats_node),
    ],
    edges=[
        ("entry", "analyzer", {"text": "input text"}),
        ("entry", "stats", {"text": "original text"}),
        ("analyzer", "stats", {"topic": "topic", "sentiment": "sentiment", "keywords": "keywords", "summary": "summary"}),
        ("stats", "exit", {"text_stats": "stats", "analysis": "analysis fields"}),
    ],
)

g.build()
out, _attrs = g.invoke({"text": "AI is developing rapidly and changing how we work."})
print(out["text_stats"])
print(out["analysis"])
```

### Imperative (alternative)

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
    instructions="You are a text analyst. Output topic/sentiment/keywords/summary.",
    prompt_template="{text}",
)
stats = g.create_node(CustomNode, name="stats", forward=stats_node)

g.edge_from_entry(analyzer, {"text": "input text"})
g.edge_from_entry(stats, {"text": "original text"})
g.create_edge(analyzer, stats, {"topic": "topic", "sentiment": "sentiment", "keywords": "keywords", "summary": "summary"})
g.edge_to_exit(stats, {"text_stats": "stats", "analysis": "analysis fields"})

g.build()
out, _attrs = g.invoke({"text": "AI is developing rapidly and changing how we work."})
print(out["text_stats"])
print(out["analysis"])
```
