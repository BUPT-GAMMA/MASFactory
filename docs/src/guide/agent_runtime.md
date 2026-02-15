# Agent Runtime (Observe → Think → Act)

This page explains what `Agent` does at runtime, with an emphasis on **how LLM context is assembled**:
inputs, `attributes`, `MessageFormatter`s, `ContextBlock`s (RAG / Memory / MCP), and tool calls.

Source of truth: `masfactory/components/agents/agent.py`

---

## 1) Observe: build system/user + chat messages

`Agent.observe(input_dict)` prepares:

- `system_prompt: str` (written into `messages[0]`)
- `user_prompt: str` (written into the last user message)
- `messages: list[dict]` (passed to `model.invoke(...)`)

In MASFactory, context assembly is intentionally **payload-first**:

1) Build a structured user payload (`dict`)
2) Inject selected context blocks into the payload as a `CONTEXT` field
3) Let the input formatter `dump(...)` convert that payload into the final user prompt text

### 1.1 Inputs come from

- **Horizontal inputs (Edge keys)**: `input_dict`
- **Vertical state (attributes)**: pulled via `pull_keys`
- **Template placeholders**: `{field}` substitution inside `instructions` / `prompt_template`
- **History messages**: from `HistoryMemory.get_messages()` (inserted as chat messages)
- **Context blocks**: from Memory/RAG/MCP providers via `get_blocks(...)` (injected into `CONTEXT`)

### 1.2 Default user payload structure

If you don't pass `formatters`, MASFactory uses:

- input formatter: `ParagraphMessageFormatter`
- output formatter: `JsonMessageFormatter`

The user payload typically contains:

- `MESSAGE TO YOU`: rendered `prompt_template`
- (optional) unused input fields (when `hide_unused_fields=False`)
- `RESPONSE FORMAT REQUIREMENTS`: provided by the output formatter
- `REQUIRED OUTPUT FIELDS AND THEIR DESCRIPTIONS`: derived from outgoing `output_keys` + `push_keys`
- `CONTEXT`: injected context text (if any)

> `CONTEXT` is injected before formatter dumping, so the same blocks will be represented differently
> depending on your input formatter.

---

## 2) Think: call the model adapter

`Agent.think(messages, settings=...)` calls:

`model.invoke(messages=..., tools=..., settings=...)`

and expects one of:

- `{"type": "content", "content": "<text>"}`
- `{"type": "tool_call", "content": [{ "id": "...", "name": "...", "arguments": {...} }, ...]}`

---

## 3) Act: execute tools and append tool results

When the model returns `tool_call`:

1) `Agent.act(...)` uses `ToolAdapter` to execute tools
2) builds tool messages shaped like `{"role":"tool","content":"...","tool_call_id":"..."}`
3) appends them to `messages` and loops back to `think(...)` until a final `content` arrives

---

## 4) How context adapters affect Agents

RAG / Memory / MCP are unified as **ContextProviders** for Agents:  
they only need to implement `get_blocks(query, top_k=...) -> list[ContextBlock]`.

### 4.1 Passive (auto-inject)

When `passive=True`, the Agent calls `get_blocks(...)` during Observe and injects rendered blocks
into the user payload as `CONTEXT`.

### 4.2 Active (on-demand retrieval via tools)

When `active=True`, the Agent provides two extra tools for the model:

- `list_context_sources()`
- `retrieve_context(source, query, top_k=...)`

This enables “reason first, retrieve later” workflows.

See: [`/guide/context_adapters`](/guide/context_adapters).

---

## 5) Examples: given inputs, what does the model receive?

These examples focus on prompt assembly, so they only call `observe()` (no model call required).

### Example A: prompt_template only (no RAG/Memory)

```python
from masfactory import Agent

agent = Agent(
    name="writer",
    model=object(),  # observe() only
    instructions="You are a concise writer.",
    prompt_template="Topic: {topic}",
)

system_prompt, user_prompt, messages = agent.observe({"topic": "What is MASFactory?"})

print(system_prompt)
print("----")
print(user_prompt)
print("----")
print([m["role"] for m in messages])
```

### Example B: passive context injection (ContextBlock → CONTEXT)

```python
from masfactory import Agent
from masfactory.adapters.context.types import ContextBlock, ContextQuery

class DummyProvider:
    context_label = "MEM"
    passive = True
    active = False
    supports_passive = True
    supports_active = True

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        return [ContextBlock(text="memory snippet", score=0.9)]

agent = Agent(
    name="writer",
    model=object(),
    instructions="You are a concise writer.",
    prompt_template="Topic: {topic}",
    memories=[DummyProvider()],
)

_, user_prompt, _ = agent.observe({"topic": "Explain DAG"})
print(user_prompt)  # contains a CONTEXT field near the end
```

You will see a `CONTEXT:` field near the end of `user_prompt`, which contains:

```
[Context]
(MEM) memory snippet
```

### Example C: active provider (on-demand via tools)

```python
from masfactory import Agent
from masfactory.adapters.context.types import ContextBlock, ContextQuery

class ActiveProvider:
    context_label = "RAG"
    passive = False
    active = True
    supports_passive = True
    supports_active = True

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        return [ContextBlock(text=f"hit for: {query.query_text}", score=0.8)]

agent = Agent(
    name="writer",
    model=object(),
    instructions="You are a concise writer.",
    prompt_template="{query}",
    retrievers=[ActiveProvider()],
)

agent.observe({"query": "MASFactory context blocks"})
print([t.__name__ for t in agent.tools])  # list_context_sources, retrieve_context, ...
```
