# 上下文接口层（RAG / Memory / MCP）

MASFactory 的一个核心目标是：把“上下文组织”从胶水代码里抽离出来，形成可复用、可组合、可测试的适配层。

在 MASFactory 中，无论你接入的是：

- 记忆（Memory，写入 + 读取）
- RAG 检索（Retrieval，只读）
- MCP（外部工具/服务的上下文源）

最终都会被统一为：**ContextBlock**，并在 `Agent.observe()` 阶段注入到 LLM 的 user prompt 中。

<ThemedDiagram light="/imgs/architecture/system-overview-light.svg" dark="/imgs/architecture/system-overview-dark.svg" alt="MASFactory 系统概览：上下文适配层在整体架构中的位置" />

---

## 去哪里看代码（以代码为准）

- Context 结构：`masfactory/adapters/context/`
- Memory：`masfactory/adapters/memory.py`
- Retrieval：`masfactory/adapters/retrieval.py`
- MCP：`masfactory/adapters/mcp.py`
- Agent 注入逻辑：`masfactory/components/agents/agent.py`

---

## 1) 如何使用：把 Memory / RAG / MCP 挂到 Agent

在 MASFactory 中，上下文源通过 `Agent(..., memories=[...], retrievers=[...])` 注入。

运行时，`Agent.observe()` 会：

1) 组装结构化的 user payload（`dict`）  
2) 向所有 `passive=True` 的 provider 拉取 `ContextBlock`  
3) 将渲染后的文本注入 `user payload["CONTEXT"]`  
4) 由输入 formatter 将 payload dump 成模型实际看到的 user prompt 文本

其中：

- `memories`：通常是**可写**的 Memory（运行时会自动写回），也可以仅作为只读上下文源使用；
- `retrievers`：通常是**只读**的 Retrieval / MCP 等上下文源。

> 提示：对 Agent 的上下文组装细节（payload 字段结构、formatter 规则等），见 [`/zh/guide/agent_runtime`](/zh/guide/agent_runtime)。

### 1.1 示例：对话历史（HistoryMemory）

`HistoryMemory` 是一个特殊的 Memory：它不会把内容注入到 `CONTEXT` 字段，而是以 **chat messages** 的形式插入到 `messages` 列表中（即模型看到的历史对话）。

```python
from masfactory import Agent, HistoryMemory

history = HistoryMemory(top_k=6)
history.insert("user", "你好，我想了解 MASFactory。")
history.insert("assistant", "好的，请问你关注的是编排、调试，还是可视化？")

agent = Agent(
    name="demo",
    model=object(),  # 这里只演示 observe()，不需要可用的 model
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    memories=[history],
)

_system_prompt, _user_prompt, messages = agent.observe({"query": "请用一句话概括 MASFactory。"})
print([m["role"] for m in messages])
# ["system", "user", "assistant", "user"]
```

### 1.2 示例：语义记忆（VectorMemory）

`VectorMemory` 会将 Memory 条目以 embedding 的方式存储，并在 Observe 阶段按 `ContextQuery.query_text` 检索，命中后以 `ContextBlock` 的形式注入 `CONTEXT`。

下面示例使用 `SimpleEmbedder`（无外部依赖，适合演示）；在生产环境中，你可以替换为 `OpenAIEmbedder` / `SentenceTransformerEmbedder` 等更高质量的 embedding。

```python
from masfactory import Agent, VectorMemory, SimpleEmbedder

embedding_fn = SimpleEmbedder(vocab_size=512).get_embedding_function()

mem = VectorMemory(
    embedding_function=embedding_fn,
    context_label="MEMORY",
    query_threshold=0.15,  # 演示用：降低阈值以便更容易命中
    passive=True,
    active=False,
)

# 你既可以在运行前预置知识，也可以依赖 Agent.step() 在每轮结束后自动写回 memory。
mem.insert("project", "MASFactory 是一个以图结构为核心的多智能体编排框架。")
mem.insert("visualizer", "MASFactory Visualizer 提供拓扑预览与运行时追踪。")

agent = Agent(
    name="demo",
    model=object(),
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    memories=[mem],
)

_, user_prompt, _ = agent.observe({"query": "MASFactory Visualizer 用来做什么？"})
print(user_prompt)  # 你会在 user prompt 中看到 CONTEXT 字段
```

### 1.3 示例：RAG 检索（Retrieval）

Retrieval 属于只读上下文源，典型用法是把项目文档、知识库或代码索引为可检索的 `ContextBlock`，并在 Observe 阶段注入 `CONTEXT`。

#### A) 小规模语料：SimpleKeywordRetriever

适合 demo 或小规模文本集合，不依赖 embedding。

```python
from masfactory import Agent, SimpleKeywordRetriever

docs = {
    "quickstart": "MASFactory builds workflows as graphs (nodes + edges).",
    "visualizer": "MASFactory Visualizer previews graphs and runtime traces.",
}

retriever = SimpleKeywordRetriever(docs, context_label="DOCS", passive=True, active=False)

agent = Agent(
    name="demo",
    model=object(),
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    retrievers=[retriever],
)

_, user_prompt, _ = agent.observe({"query": "Visualizer 是做什么的？"})
print(user_prompt)
```

#### B) 目录检索：FileSystemRetriever（embedding）

适合把一个目录下的文件（如 Markdown、纯文本等）作为语料建立索引，并基于 embedding 进行相似度检索。

```python
from masfactory import Agent, FileSystemRetriever, SimpleEmbedder

embedding_fn = SimpleEmbedder(vocab_size=512).get_embedding_function()

retriever = FileSystemRetriever(
    docs_dir="./docs",             # 你的语料目录
    file_extension=".md",          # 过滤扩展名
    embedding_function=embedding_fn,
    similarity_threshold=0.15,     # 演示用：降低阈值
    cache_path=".cache/docs.json", # 可选：缓存 embeddings
    context_label="DOCS_FS",
)

agent = Agent(
    name="demo",
    model=object(),
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    retrievers=[retriever],
)

_, user_prompt, _ = agent.observe({"query": "如何安装 MASFactory？"})
print(user_prompt)
```

### 1.4 示例：通过 MCP 接入外部上下文源

当上下文来自外部服务（企业知识库、搜索系统、数据平台等），你可以用 `MCP` 适配器把“外部检索结果”映射为 `ContextBlock`。

```python
from masfactory import Agent
from masfactory.adapters.context.types import ContextQuery
from masfactory.adapters.mcp import MCP

def call_mcp(query: ContextQuery, top_k: int):
    # 这里用一个 stub 演示：实际实现应当调用你的 MCP server/tool，并返回 item 列表。
    return [
        {"text": f"[Wiki] {query.query_text} 的相关条目", "uri": "mcp://wiki/entry/1", "score": 0.92},
    ]

wiki = MCP(name="WIKI", call=call_mcp, passive=True, active=False)

agent = Agent(
    name="demo",
    model=object(),
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    retrievers=[wiki],  # MCP 作为“上下文源”挂到 Agent 即可
)

_, user_prompt, _ = agent.observe({"query": "MASFactory 的主要组件有哪些？"})
print(user_prompt)
```

### 1.5 同时使用多个上下文源

你可以同时配置多个 Memory/Retrieval/MCP provider。它们会被统一渲染并注入到同一个 `CONTEXT` 字段中（默认渲染器会为每条 block 标注来源标签）。

```python
from masfactory import Agent, HistoryMemory, VectorMemory, SimpleEmbedder, SimpleKeywordRetriever
from masfactory.adapters.mcp import MCP
from masfactory.adapters.context.types import ContextQuery

embedding_fn = SimpleEmbedder(vocab_size=512).get_embedding_function()

history = HistoryMemory(top_k=6)
mem = VectorMemory(embedding_function=embedding_fn, context_label="MEMORY", query_threshold=0.15)
mem.insert("note", "Graph 由 nodes 与 edges 组成。")

docs = SimpleKeywordRetriever({"doc": "Visualizer previews graphs."}, context_label="DOCS")

def call_mcp(query: ContextQuery, top_k: int):
    return [{"text": "外部知识片段", "uri": "mcp://demo"}]

wiki = MCP(name="WIKI", call=call_mcp)

agent = Agent(
    name="demo",
    model=object(),
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    memories=[history, mem],
    retrievers=[docs, wiki],
)

_, user_prompt, messages = agent.observe({"query": "解释 Visualizer 的作用。"})
print([m["role"] for m in messages])  # 含 history messages
print(user_prompt)                   # 含 CONTEXT 字段
```

---

## 2) Passive vs Active：自动注入 vs 按需检索

每个 provider 都可以配置两种工作模式：

### 2.1 Passive（自动注入到 `CONTEXT`）

- `passive=True` 时，Agent 会在 Observe 阶段自动调用 `get_blocks(...)`
- 结果会按策略筛选/去重后注入到 user payload 的 `CONTEXT` 字段
- 之后由输入 formatter `dump(...)` 决定最终文本形态

### 2.2 Active（作为工具供模型按需调用）

- `active=True` 时，Agent 会在本轮临时为模型提供两个工具：
  - `list_context_sources()`
  - `retrieve_context(source, query, top_k=...)`
- 适用于“先推理后检索”的场景：模型先读任务再决定要不要检索、检索什么

> 约定：多数内置 provider 采用 `top_k=0` 表示“尽可能多返回”，`top_k<0` 表示返回空。

#### 示例：把检索器作为 Tool 提供给模型（Active Retrieval）

下面示例把一个 `SimpleKeywordRetriever` 配置为 `active=True`（`passive=False`），使其不自动注入 `CONTEXT`，而是通过工具按需检索：

```python
from masfactory import Agent, SimpleKeywordRetriever

docs = {
    "quickstart": "MASFactory builds workflows as graphs (nodes + edges).",
    "visualizer": "MASFactory Visualizer previews graphs and runtime traces.",
}

retriever = SimpleKeywordRetriever(
    docs,
    context_label="DOCS",
    passive=False,  # 不自动注入 CONTEXT
    active=True,    # 作为工具暴露给模型
)

agent = Agent(
    name="demo",
    model=object(),  # 这里只演示 observe() 生成 tools，不需要可用的 model
    instructions="需要外部信息时，请先列出 source，再按需检索。",
    prompt_template="{query}",
    retrievers=[retriever],
)

agent.observe({"query": "What is MASFactory Visualizer?"})
print([t.__name__ for t in agent.tools])
# 包含：list_context_sources / retrieve_context
```

#### 结合你自己的工具函数

Active provider 的检索工具会与 `Agent(tools=[...])` 传入的工具**一起**暴露给模型。

```python
from datetime import datetime, timezone
from masfactory import Agent, SimpleKeywordRetriever

def get_utc_now() -> str:
    \"\"\"Get current UTC time in ISO format.\"\"\"
    return datetime.now(timezone.utc).isoformat()

retriever = SimpleKeywordRetriever({"doc": "..."}, passive=False, active=True)

agent = Agent(
    name="demo",
    model=object(),
    instructions="必要时可调用工具。",
    prompt_template="{query}",
    tools=[get_utc_now],
    retrievers=[retriever],
)

agent.observe({"query": "..."})
print([t.__name__ for t in agent.tools])
```

---

## 3) 两个关键数据结构：ContextQuery / ContextBlock

### ContextBlock：上下文的最小单元

`ContextBlock` 是“要注入到 LLM 的一段上下文”，并携带可选的可观测信息（来源、分数、元数据等）：

- `text`：要注入的文本（必填）
- `uri / chunk_id`：来源定位（可选）
- `score`：相关性分数（可选）
- `title / metadata / dedupe_key`：展示与去重（可选）

### ContextQuery：传给 provider 的标准查询

MASFactory 会把当前执行上下文规范化为 `ContextQuery`，常用字段包括：

- `query_text`：本轮的“检索 query”（从输入字段中尽力提取）
- `inputs`：本轮输入字段（水平消息）+ 渲染模板时用到的字段
- `attributes`：本节点 attributes（垂直状态）
- `node_name`：当前节点名
- `messages`：已注入的历史消息（若存在）

你的 provider 可以利用这些字段决定检索策略与输出格式。

---

## 4) 如何扩展：实现一个 ContextProvider

MASFactory 对上下文源的最低要求非常简单：实现 `get_blocks(...)`。

```python
from masfactory.adapters.context.types import ContextBlock, ContextQuery

class MyProvider:
    context_label = "MY_SOURCE"
    passive = True
    active = False
    supports_passive = True
    supports_active = True

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        return [ContextBlock(text="...")]
```

然后把它挂到 Agent 上（`memories=[...]` 或 `retrievers=[...]` 都可以；Agent 以“ContextProvider”对待它们）。

---

## 5) 扩展示例：接入 MemoryOS（Native / MCP）

MASFactory 内置了两种形态的 MemoryOS 适配：

- **Native（in-process）**：实现 `Memory`（可写入，也可读出 ContextBlock）
- **MCP（out-of-process）**：通过 `MCP` 传输把返回映射成 ContextBlock

源码：`masfactory/integrations/memoryos.py`

### 5.1 Native：MemoryOSMemory（走 Memory 接口）

```python
from masfactory import Agent
from masfactory.adapters.context.types import ContextQuery
from masfactory.integrations.memoryos import MemoryOSMemory

def memoryos_retrieve(query: ContextQuery, top_k: int):
    # TODO: 替换为你的 MemoryOS client 调用
    return [
        {"text": f"[MemoryOS] hit for: {query.query_text}", "uri": "memoryos://demo", "score": 0.9},
    ]

mem = MemoryOSMemory(
    retrieve=memoryos_retrieve,
    insert_fn=lambda k, v: None,  # 可选：把 Agent 输出写回 MemoryOS
    passive=True,
    active=False,
)

agent = Agent(
    name="demo",
    model=object(),  # 这里只演示 observe() 组装效果
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    memories=[mem],
)

_, user_prompt, _ = agent.observe({"query": "Explain context blocks"})
print(user_prompt)  # 末尾会出现 CONTEXT 字段
```

### 5.2 MCP：make_memoryos_mcp（走 MCP 上下文源）

```python
from masfactory import Agent
from masfactory.adapters.context.types import ContextQuery
from masfactory.integrations.memoryos import make_memoryos_mcp

def mcp_call(query: ContextQuery, top_k: int):
    # TODO: 替换为你对 MCP server/tool 的调用
    return [{"text": f"[MemoryOS/MCP] hit: {query.query_text}", "uri": "mcp://memoryos"}]

mcp_provider = make_memoryos_mcp(call=mcp_call, passive=True, active=False)

agent = Agent(
    name="demo",
    model=object(),
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    retrievers=[mcp_provider],  # MCP 作为“上下文源”挂到 Agent 即可
)

_, user_prompt, _ = agent.observe({"query": "What is MemoryOS?"})
print(user_prompt)
```

---

## 6) 扩展示例：接入 UltraRAG（Native / MCP）

MASFactory 提供 UltraRAG 的两种适配形态：

- **Native（in-process）**：`UltraRAGRetriever`（走 Retrieval 接口）
- **MCP（out-of-process）**：`make_ultrarag_mcp(...)`（走 MCP）

源码：`masfactory/integrations/ultrarag.py`

### 6.1 Native：UltraRAGRetriever（走 RAG/Retrieval）

```python
from masfactory import Agent
from masfactory.adapters.context.types import ContextQuery
from masfactory.integrations.ultrarag import UltraRAGRetriever

def ultrarag_retrieve(query: ContextQuery, top_k: int):
    # TODO: 替换为你的 UltraRAG client 调用
    return [
        {"text": f"[UltraRAG] doc for: {query.query_text}", "uri": "ultrarag://doc/1", "score": 0.82},
    ]

rag = UltraRAGRetriever(retrieve=ultrarag_retrieve, passive=True, active=False)

agent = Agent(
    name="demo",
    model=object(),
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    retrievers=[rag],
)

_, user_prompt, _ = agent.observe({"query": "How does MASFactory work?"})
print(user_prompt)
```

### 6.2 MCP：make_ultrarag_mcp（走 MCP）

```python
from masfactory import Agent
from masfactory.adapters.context.types import ContextQuery
from masfactory.integrations.ultrarag import make_ultrarag_mcp

def mcp_call(query: ContextQuery, top_k: int):
    # TODO: 替换为你对 MCP server/tool 的调用
    return [{"text": f"[UltraRAG/MCP] {query.query_text}", "uri": "mcp://ultrarag"}]

mcp_rag = make_ultrarag_mcp(call=mcp_call, passive=True, active=False)

agent = Agent(
    name="demo",
    model=object(),
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    retrievers=[mcp_rag],
)

_, user_prompt, _ = agent.observe({"query": "RAG with context blocks"})
print(user_prompt)
```
