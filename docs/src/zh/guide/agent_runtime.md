# Agent 运行机制（Observe → Think → Act）

这页聚焦 `Agent` 在运行时到底做了什么，尤其是 **LLM 上下文是如何组建的**：  
输入字段、`attributes`、`MessageFormatter`、`ContextBlock`（RAG / Memory / MCP）以及工具调用如何一起工作。

源码参考：`masfactory/components/agents/agent.py`

---

## 1) Observe：组装 system/user 与 messages

`Agent.observe(input_dict)` 的职责是把一次执行所需的信息组织成：

- `system_prompt: str`（写入 `messages[0]`）
- `user_prompt: str`（写入最后一条 user message）
- `messages: list[dict]`（传给 `model.invoke(...)` 的 chat messages）

在 MASFactory 里，**上下文的组装不是“拼接字符串”**，而是：

1) 先把信息组织成结构化 `dict`（user payload）  
2) 再交给输入 formatter `dump(...)` 变成字符串  
3) 再把 RAG/Memory/MCP 产出的 `ContextBlock` 注入到 user payload 的 `CONTEXT` 字段

### 1.1 输入来自哪里？

Observe 阶段会综合这些信息源：

- **水平输入（Edge keys）**：本轮 `input_dict`
- **垂直状态（attributes）**：通过 `pull_keys` 拉取到的本节点 `attributes`
- **模板占位符**：`instructions` / `prompt_template` 中的 `{field}` 替换
- **历史消息**：来自 `HistoryMemory.get_messages()`（以 chat messages 形式插入）
- **上下文块**：来自 Memory/RAG/MCP 的 `get_blocks(...)`（注入 `CONTEXT` 字段）

### 1.2 user payload 的默认结构

默认情况下（未显式配置 `formatters`），`Agent` 使用：

- 输入 formatter：`ParagraphMessageFormatter`（把 dict dump 成“段落式 KV”文本）
- 输出 formatter：`JsonMessageFormatter`（把模型输出解析为 JSON dict）

user payload 大致包含：

- `MESSAGE TO YOU`：`prompt_template` 渲染后的内容
- （可选）未被模板消费的字段：`hide_unused_fields=False` 时会追加
- `RESPONSE FORMAT REQUIREMENTS`：由输出 formatter 提供的格式要求说明
- `REQUIRED OUTPUT FIELDS AND THEIR DESCRIPTIONS`：根据出边 `output_keys` + `push_keys` 生成的字段约束
- `CONTEXT`：由上下文适配层注入的上下文文本（如果有）

> `CONTEXT` 的注入发生在 formatter `dump(...)` 之前，所以 **同一套上下文块** 在不同 formatter 下会以不同格式呈现。

---

## 2) Think：调用模型

`Agent.think(messages, settings=...)` 会调用：

`model.invoke(messages=..., tools=..., settings=...)`

并要求返回规范化结果之一：

- `{"type": "content", "content": "<text>"}`  
- `{"type": "tool_call", "content": [{ "id": "...", "name": "...", "arguments": {...} }, ...]}`

---

## 3) Act：执行工具并回填结果

当模型返回 `tool_call` 时：

1) `Agent.act(...)` 用 `ToolAdapter` 执行工具  
2) 产出 `{"role":"tool","content":"...","tool_call_id":"..."}` 形式的 tool messages  
3) 追加到 `messages` 再次进入 `think(...)`，直到返回最终 `content`

---

## 4) 上下文适配层如何影响 Agent？

RAG / Memory / MCP 都统一为 **ContextProvider**：  
对 Agent 来说，它们只需要实现 `get_blocks(query, top_k=...) -> list[ContextBlock]`。

### 4.1 Passive（自动注入）

当 provider 配置为 `passive=True` 时，Agent 会在 Observe 阶段自动调用 `get_blocks(...)`，并把结果注入 user payload 的 `CONTEXT` 字段。

### 4.2 Active（按需检索：工具调用）

当 provider 配置为 `active=True` 时，Agent 会在本轮临时注入两个工具：

- `list_context_sources()`：列出可用 source（含去重后的名字）
- `retrieve_context(source, query, top_k=...)`：按 source 拉取 blocks，并返回“结构化 blocks + 渲染文本”

这样模型可以 **先看当前对话与任务**，再决定是否触发检索。

完整细节与示例见：[`/zh/guide/context_adapters`](/zh/guide/context_adapters)。

---

## 5) 示例：给定输入，LLM 实际收到什么？

下面示例的重点是 **观察上下文组装结果**，所以只调用 `observe()`（不会真的请求模型）。

### 示例 A：只有 prompt_template（无 RAG/Memory）

```python
from masfactory import Agent

agent = Agent(
    name="writer",
    model=object(),  # 这里只演示 observe()，不需要可用的 model
    instructions="你是一个简洁的写作者。",
    prompt_template="主题：{topic}",
)

system_prompt, user_prompt, messages = agent.observe({"topic": "MASFactory 是什么？"})

print(system_prompt)
print("----")
print(user_prompt)
print("----")
print([m["role"] for m in messages])
```

你会看到：

- `messages` 形如：`["system", "user"]`
- `user_prompt` 里包含：
  - `MESSAGE TO YOU: ...`
  - 输出 formatter 的格式要求
  - 由出边约束生成的必填字段说明（如果该 Agent 有出边）

### 示例 B：注入一段 passive 上下文（ContextBlock → CONTEXT）

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
    instructions="你是一个简洁的写作者。",
    prompt_template="主题：{topic}",
    memories=[DummyProvider()],
)

_, user_prompt, _ = agent.observe({"topic": "解释 DAG"})
print(user_prompt)
```

你会在 `user_prompt` 末尾看到 `CONTEXT:` 字段，其中包含：

```
[Context]
(MEM) memory snippet
```

### 示例 C：Active provider（不自动注入，用工具按需拉取）

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
    instructions="你是一个简洁的写作者。",
    prompt_template="{query}",
    retrievers=[ActiveProvider()],
)

agent.observe({"query": "MASFactory context blocks"})
print([t.__name__ for t in agent.tools])
```

此时 `agent.tools` 会包含 `list_context_sources` / `retrieve_context`，模型可按需检索。

