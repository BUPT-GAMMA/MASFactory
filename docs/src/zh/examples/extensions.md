# 扩展接口（Model / 上下文适配 / MessageFormatter）

MASFactory 的核心抽象很少，但扩展点很清晰。你通常会扩展三类能力：

- `Model`：接入新的 LLM / OpenAI 兼容服务
- 上下文适配（RAG / Memory / MCP）：把外部信息变成可注入的 `ContextBlock`
- `MessageFormatter`：定制 LLM 输入/输出协议（JSON、段落式 KV、Markdown 等）

## 示意图
<ThemedDiagram light="/imgs/message/overview-light.svg" dark="/imgs/message/overview-dark.svg" alt="扩展点在整体消息流中的位置（总览）" />

---

## 1) 自定义 Model（最小骨架）

`Model.invoke(...)` 必须返回其一：

- `{"type": ModelResponseType.CONTENT, "content": "..."}` 或
- `{"type": ModelResponseType.TOOL_CALL, "content": [{"id": "...", "name": "...", "arguments": {...}}, ...]}`

```python
from masfactory.adapters.model import Model, ModelResponseType


class MyModel(Model):
    def invoke(self, messages: list[dict], tools: list[dict] | None, settings: dict | None = None, **kwargs) -> dict:
        # TODO: 调用你的服务，把 messages/tools/settings 转成它需要的请求格式
        text = "..."
        return {"type": ModelResponseType.CONTENT, "content": text}
```

参考源码：`masfactory/adapters/model.py`。

---

## 2) 上下文适配（RAG / Memory / MCP）：最小骨架

MASFactory 把“可注入到 LLM 的上下文”统一为 `ContextBlock`。  
无论是 Memory、RAG 还是 MCP，在 Agent 看来都是“上下文源”，都通过同一套接口读取：

`get_blocks(query: ContextQuery, top_k: int = 8) -> list[ContextBlock]`

完整概念与更多示例见：[`/zh/guide/context_adapters`](/zh/guide/context_adapters)。

### 2.1 自定义 Memory（可写入 + 可注入）

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
        # 可选：按你的后端语义实现
        return None

    def delete(self, key: str, index: int = -1):
        # 可选：按你的后端语义实现
        return None

    def reset(self):
        self._store = []

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        # 这里给个最简单的实现：把 store 最后 N 条作为上下文注入
        limit = len(self._store) if int(top_k) == 0 else max(int(top_k), 0)
        if limit <= 0:
            return []
        return [ContextBlock(text=line) for line in self._store[-limit:]]
```

### 2.2 自定义 RAG（Retrieval，只读）

```python
from masfactory.adapters.context.types import ContextBlock, ContextQuery
from masfactory.adapters.retrieval import Retrieval


class MyRetriever(Retrieval):
    def __init__(self):
        super().__init__(context_label="MY_RAG")

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        # TODO: 调用你的向量库/检索系统，映射为 ContextBlock
        return [ContextBlock(text=f"hit for: {query.query_text}", score=0.8)]
```

### 2.3 MCP：用内置 `MCP` 适配器把返回映射为 ContextBlock

```python
from masfactory.adapters.context.types import ContextQuery
from masfactory.adapters.mcp import MCP


def call(query: ContextQuery, top_k: int):
    # TODO: 调用 MCP server/tool，返回 iterable items（每项至少包含 text）
    return [{"text": f"[MCP] {query.query_text}", "uri": "mcp://demo"}]


mcp_provider = MCP(name="MyMCP", call=call, passive=True, active=False)
```

---

## 3) 自定义 MessageFormatter（最小骨架）

Formatter 负责把 LLM 的字符串输出解析为 `dict`，以及把 dict payload dump 成输入 prompt 文本。

```python
from masfactory.core.message import MessageFormatter


class MyFormatter(MessageFormatter):
    def __init__(self):
        super().__init__()
        self._is_input_formatter = True
        self._is_output_formatter = True
        self._agent_introducer = "你的格式说明（会写进 Agent prompt）"

    def format(self, message: str) -> dict:
        return {"raw": message}

    def dump(self, message: dict) -> str:
        return str(message)
```

参考源码：`masfactory/core/message/`。

---

## 4) 测试 demo：两种接入方式都跑一下

### 4.1 demo A（离线可跑）：CustomNode + Memory（写入/重置）

这个 demo 不依赖 LLM，适合验证你的 Memory 写入与生命周期行为。

#### 4.1A 声明式（主推）

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

#### 4.1B 命令式（备选）

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

### 4.2 demo B：验证上下文注入（ContextBlock → `CONTEXT`）

这个 demo 只调用 `Agent.observe()` 来观察 prompt 组装结果，不需要真的请求模型。

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
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    retrievers=[DummyRAG()],
)

_, user_prompt, _ = agent.observe({"query": "Explain MCP"})
print(user_prompt)  # 末尾会出现 CONTEXT 字段
```

