# Tool Calling (Tools)

This chapter explains how to attach **Tools** (Python callables) to an `Agent`, and how MASFactory turns them into “function tools” that a model can call.

Notes:

- Memory/RAG/MCP are primarily for **supplying context** (injecting `ContextBlock` into `CONTEXT`).
- Tools are for **executing actions** (file IO, network calls, integrations, etc.) when the model decides it needs them.

Code reference: `masfactory/adapters/tool_adapter.py`, `masfactory/components/agents/agent.py`

---

## 1) Attach tools to an Agent

Pass tools via `tools=[...]` when creating an agent:

```python
from masfactory import Agent, OpenAIModel

def get_utc_now() -> str:
    """Get current UTC time in ISO format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

agent = Agent(
    name="demo",
    model=OpenAIModel(api_key="...", model_name="gpt-4o-mini"),
    instructions="You may call tools when needed.",
    prompt_template="{query}",
    tools=[get_utc_now],
)
```

You can also put tools into a `NodeTemplate` for reuse:

```python
from masfactory import Agent, NodeTemplate

BaseAgent = NodeTemplate(Agent, tools=[get_utc_now])
```

---

## 2) Define a tool (signature + docstring)

MASFactory builds tool schemas from **function signatures** and **docstrings**:

- function name → tool name
- parameter names + type hints → JSON Schema `parameters`
- parameter docs → schema `description`
- default values → schema `default`

Recommended rules:

1) Use JSON-friendly types: `str/int/float/bool/dict/list`, plus Optional/Union combinations.  
2) Provide clear parameter docstrings (semantics, units, constraints).  
3) Avoid `*args/**kwargs` (they are not included in schemas).

### Example: a “search” tool

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
    hits = [
        {"title": "MASFactory overview", "snippet": f"hit for: {query}"},
    ][: max(1, int(top_k))]
    return {"hits": hits}
```

Attach it:

```python
from masfactory import Agent

agent = Agent(
    name="demo",
    model=object(),  # observe() only
    instructions="Call search_docs when you need external info.",
    prompt_template="{query}",
    tools=[search_docs],
)

agent.observe({"query": "..."})
print([t.__name__ for t in agent.tools])
```

---

## 3) Runtime: Observe → Think → Act

With tools configured on an agent:

1) **Observe**: MASFactory passes tool schemas into `model.invoke(...)`
2) **Think**: the model may return `tool_call` items (tool name + arguments)
3) **Act**: MASFactory executes the Python callable and appends tool-result messages, then continues thinking

For the full flow, see: [`Agent Runtime (Observe/Think/Act)`](/guide/agent_runtime).

---

## 4) Relation to Memory/RAG/MCP: Active providers also inject tools

If you configure a context source with `active=True` (and `passive=False`), MASFactory injects two additional tools for that run:

- `list_context_sources()`
- `retrieve_context(source, query, top_k=...)`

This enables “retrieve on demand” instead of auto-injecting blocks into `CONTEXT` during Observe.

See the Active examples in: [`Context Adapters (RAG / Memory / MCP)`](/guide/context_adapters).

