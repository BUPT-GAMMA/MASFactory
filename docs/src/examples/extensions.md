# Extension Interfaces (Model / Context Adapters / MessageFormatter)

MASFactory keeps the orchestration core small, and pushes integrations into a few clear extension points:

- `Model`: integrate a new LLM provider / an OpenAI-compatible endpoint
- Context adapters (RAG / Memory / MCP): turn external information into injectable `ContextBlock`s
- `MessageFormatter`: customize the LLM I/O protocol (JSON, paragraph-style KV, Markdown, etc.)

## Diagram
<ThemedDiagram light="/imgs/message/overview-en-light.svg" dark="/imgs/message/overview-en-dark.svg" alt="Extension points in context (message passing overview)" />

---

## 1) Custom Model (minimal skeleton)

`Model.invoke(...)` must return either:

- `{"type": ModelResponseType.CONTENT, "content": "..."}` or
- `{"type": ModelResponseType.TOOL_CALL, "content": [{"id": "...", "name": "...", "arguments": {...}}, ...]}`

```python
from masfactory.adapters.model import Model, ModelResponseType


class MyModel(Model):
    def invoke(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        settings: dict | None = None,
        **kwargs,
    ) -> dict:
        # TODO: call your provider with (messages/tools/settings)
        text = "..."
        return {"type": ModelResponseType.CONTENT, "content": text}
```

Reference implementation: `masfactory/adapters/model.py`.

---

## 2) Context adapters (RAG / Memory / MCP): minimal skeletons

MASFactory standardizes all “injectable context” as `ContextBlock`.  
Whether it's RAG, Memory, or MCP, Agents read them via the same contract:

`get_blocks(query: ContextQuery, top_k: int = 8) -> list[ContextBlock]`

For concepts and more examples, see: [`/guide/context_adapters`](/guide/context_adapters).

### 2.1 Custom Memory (writable + injectable)

```python
from masfactory.adapters.context.types import ContextBlock, ContextQuery
from masfactory.adapters.memory import Memory


class MyMemory(Memory):
    def __init__(self):
        super().__init__(context_label="MY_MEMORY")
        self._store: list[str] = []

    def insert(self, key: str, value: str):
        self._store.append(f"{key}: {value}")

    def update(self, key: str, value: str):
        return None

    def delete(self, key: str, index: int = -1):
        return None

    def reset(self):
        self._store = []

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        limit = len(self._store) if int(top_k) == 0 else max(int(top_k), 0)
        if limit <= 0:
            return []
        return [ContextBlock(text=line) for line in self._store[-limit:]]
```

### 2.2 Custom RAG (Retrieval, read-only)

```python
from masfactory.adapters.context.types import ContextBlock, ContextQuery
from masfactory.adapters.retrieval import Retrieval


class MyRetriever(Retrieval):
    def __init__(self):
        super().__init__(context_label="MY_RAG")

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        # TODO: call your vector DB / search engine, map results into ContextBlock
        return [ContextBlock(text=f"hit for: {query.query_text}", score=0.8)]
```

### 2.3 MCP: use the built-in `MCP` adapter

```python
from masfactory.adapters.context.types import ContextQuery
from masfactory.adapters.mcp import MCP


def call(query: ContextQuery, top_k: int):
    # TODO: call an MCP server/tool; return items (each must include at least `text`)
    return [{"text": f"[MCP] {query.query_text}", "uri": "mcp://demo"}]


mcp_provider = MCP(name="MyMCP", call=call, passive=True, active=False)
```

---

## 3) Custom MessageFormatter (minimal skeleton)

Formatters parse model output into a `dict`, and dump dict payloads into input prompt text.

```python
from masfactory.core.message import MessageFormatter


class MyFormatter(MessageFormatter):
    def __init__(self):
        super().__init__()
        self._is_input_formatter = True
        self._is_output_formatter = True
        self._agent_introducer = "Your formatting rules (inserted into Agent prompts)."

    def format(self, message: str) -> dict:
        return {"raw": message}

    def dump(self, message: dict) -> str:
        return str(message)
```

Reference: `masfactory/core/message/`.

---

## 4) Test demos (run both styles)

### 4.1 Demo A (offline runnable): CustomNode + Memory (write/reset)

This demo does not require an LLM. It's a quick way to validate your memory adapter lifecycle.

#### 4.1A Declarative (recommended)

```python
from masfactory import CustomNode, NodeTemplate, RootGraph
from masfactory.adapters.memory import Memory
from masfactory.adapters.context.types import ContextBlock, ContextQuery


class CounterMemory(Memory):
    def __init__(self):
        super().__init__(context_label="COUNTER", passive=False, active=False)
        self._n = 0

    def insert(self, key: str, value: str):
        self._n += 1

    def update(self, key: str, value: str):
        return None

    def delete(self, key: str, index: int = -1):
        return None

    def reset(self):
        self._n = 0

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        return []

    def count(self) -> int:
        return self._n


mem = CounterMemory()

def step(_d: dict, _attrs: dict, memories: list[Memory] | None):
    (memories or [])[0].insert("k", "v")
    return {"ok": True}


Step = NodeTemplate(CustomNode, forward=step, memories=[mem])

g = RootGraph(
    name="memory_demo",
    nodes=[("step", Step)],
    edges=[("entry", "step", {}), ("step", "exit", {"ok": "ok"})],
)

g.build()
g.invoke({})
print(mem.count())  # 1
```

#### 4.1B Imperative (alternative)

```python
from masfactory import CustomNode, RootGraph
from masfactory.adapters.memory import Memory
from masfactory.adapters.context.types import ContextBlock, ContextQuery


class CounterMemory(Memory):
    def __init__(self):
        super().__init__(context_label="COUNTER", passive=False, active=False)
        self._n = 0

    def insert(self, key: str, value: str):
        self._n += 1

    def update(self, key: str, value: str):
        return None

    def delete(self, key: str, index: int = -1):
        return None

    def reset(self):
        self._n = 0

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        return []

    def count(self) -> int:
        return self._n


mem = CounterMemory()

def step(_d: dict, _attrs: dict, memories: list[Memory] | None):
    (memories or [])[0].insert("k", "v")
    return {"ok": True}


g = RootGraph(name="memory_demo_imp")
node = g.create_node(CustomNode, name="step", forward=step, memories=[mem])
g.edge_from_entry(node, {})
g.edge_to_exit(node, {"ok": "ok"})

g.build()
g.invoke({})
print(mem.count())  # 1
```

### 4.2 Demo B: Verify context injection (ContextBlock → `CONTEXT`)

This demo only calls `Agent.observe()` to inspect prompt assembly. No model call required.

```python
from masfactory import Agent
from masfactory.adapters.context.types import ContextBlock, ContextQuery


class DummyRAG:
    context_label = "RAG"
    passive = True
    active = False
    supports_passive = True
    supports_active = True

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        return [ContextBlock(text=f"hit for: {query.query_text}", score=0.9)]


agent = Agent(
    name="demo",
    model=object(),
    instructions="You are a concise assistant.",
    prompt_template="{query}",
    retrievers=[DummyRAG()],
)

_, user_prompt, _ = agent.observe({"query": "Explain MCP"})
print(user_prompt)  # a `CONTEXT` field is injected near the end
```

