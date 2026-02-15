# 工具调用（Tools）

本章介绍如何为 `Agent` 添加 **Tools**（工具函数），以及 MASFactory 如何把 Python 可调用对象转化为大模型可调用的 “function tools”。

> 说明：Tools 与 “上下文接口层（Memory/RAG/MCP）”相互独立。  
> - Memory/RAG/MCP 主要用于**向模型提供上下文**（`ContextBlock` 注入 `CONTEXT`）；  
> - Tools 用于**让模型触发可执行动作**（读写文件、发起请求、调用外部系统等）。

源码参考：`masfactory/adapters/tool_adapter.py`、`masfactory/components/agents/agent.py`

---

## 1) 如何给 Agent 添加 Tools

你可以在创建 `Agent` 时直接传入 `tools=[...]`：

```python
from masfactory import Agent, OpenAIModel

def get_utc_now() -> str:
    """Get current UTC time in ISO format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

agent = Agent(
    name="demo",
    model=OpenAIModel(api_key="...", model_name="gpt-4o-mini"),
    instructions="你可以在需要时调用工具。",
    prompt_template="{query}",
    tools=[get_utc_now],
)
```

也可以把 tools 写进 `NodeTemplate`，用于复用同一套工具集合：

```python
from masfactory import Agent, NodeTemplate

BaseAgent = NodeTemplate(Agent, tools=[get_utc_now])
```

---

## 2) 如何声明一个 Tool（函数签名 + docstring）

MASFactory 会基于**函数签名**与 **docstring** 自动生成工具 schema：

- 函数名 → tool name
- 参数名/类型注解 → JSON Schema `parameters`
- docstring 中的参数描述 → schema 的 `description`
- 默认值 → schema 的 `default`

因此，建议遵循以下规则：

1) **使用可序列化的入参/出参类型**：`str/int/float/bool/dict/list`，以及它们的 Optional/Union 组合。  
2) **为参数写清晰的 docstring**：至少解释每个参数的语义与单位/范围约束。  
3) 避免 `*args/**kwargs`：它们不会被加入 schema。

### 示例：一个“可检索”的工具

```python
from typing import Any

def search_docs(query: str, top_k: int = 5) -> dict[str, Any]:
    """Search a local doc index.

    Args:
        query: Search keywords.
        top_k: Max number of hits to return.

    Returns:
        A dict with `hits`, each hit contains `title` and `snippet`.
    """
    # 这里只演示返回结构，真实实现可接入你自己的索引或检索服务。
    hits = [
        {"title": "MASFactory overview", "snippet": f"hit for: {query}"},
    ][: max(1, int(top_k))]
    return {"hits": hits}
```

将其加入 Agent：

```python
from masfactory import Agent

agent = Agent(
    name="demo",
    model=object(),  # 这里只演示 schema 生成，不需要可用的 model
    instructions="需要信息时可调用 search_docs。",
    prompt_template="{query}",
    tools=[search_docs],
)

agent.observe({"query": "..."})
print([t.__name__ for t in agent.tools])
```

---

## 3) 运行时机制：Observe → Think → Act

当你为 `Agent` 配置了 tools：

1) **Observe**：MASFactory 会把工具 schema 传给 `model.invoke(...)`  
2) **Think**：模型可能返回 `tool_call`（指定工具名与参数）  
3) **Act**：MASFactory 调用对应 Python 函数，并把结果作为 tool message 回填，再进入下一轮 Think

这一机制的详细流程见：[Agent 运行机制](/zh/guide/agent_runtime)。

---

## 4) 与 Memory/RAG/MCP 的关系：Active Provider 也会注入 Tools

当你把某个上下文源配置为 `active=True`（并且 `passive=False`）时，MASFactory 会在本轮额外注入两个工具：

- `list_context_sources()`：列出可用上下文源
- `retrieve_context(source, query, top_k=...)`：从指定 source 拉取 `ContextBlock`

这样模型可以“按需检索”，而不是在 Observe 阶段自动把上下文写入 `CONTEXT`。

具体用法见：[上下文接口层（RAG / Memory / MCP）](/zh/guide/context_adapters) 的 Active 示例。

