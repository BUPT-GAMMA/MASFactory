# 模型适配器（Model）

MASFactory 使用 **模型适配器（Model）** 屏蔽不同大模型提供方的接口差异，并为 `Agent` 提供一套稳定、可测试的调用契约。你可以在同一套编排代码中自由切换 OpenAI 兼容接口、Anthropic、Gemini 等模型实现。

---

## 去哪里看代码（以代码为准）

- `Model` 接口与内置实现：`masfactory/adapters/model.py`

---

## 1) 如何使用 Model（最小示例）

模型适配器是 `Agent` 的构造参数之一。你只需要创建一个 `Model` 实例，并传给 `Agent`（或通过 `NodeTemplate` 复用同一份配置）。

下面示例展示了一个最小两阶段 Agent 工作流：`ENTRY → analyze → answer → EXIT`。

```python
import os
from masfactory import RootGraph, Agent, NodeTemplate, OpenAIModel

model = OpenAIModel(
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL") or None,
    model_name=os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
)

BaseAgent = NodeTemplate(Agent, model=model)

g = RootGraph(
    name="qa_two_stage",
    nodes=[
        ("analyze", BaseAgent(instructions="你是问题分析专家。", prompt_template="用户问题：{query}")),
        ("answer", BaseAgent(instructions="你是解决方案专家。", prompt_template="问题：{query}\n分析：{analysis}")),
    ],
    edges=[
        ("entry", "analyze", {"query": "用户问题"}),
        ("analyze", "answer", {"query": "原始问题", "analysis": "分析结果"}),
        ("answer", "exit", {"answer": "最终回答"}),
    ],
)

g.build()
out, _attrs = g.invoke({"query": "我想学习 Python，但不知道从哪里开始"})
print(out["answer"])
```

---

## 2) 内置模型适配器（可直接使用）

MASFactory 当前内置以下模型适配器（均可从 `masfactory` 直接导入）：

### `OpenAIModel`（OpenAI 兼容接口）

```python
from masfactory import OpenAIModel

model = OpenAIModel(
    model_name="gpt-4o-mini",
    api_key="...",
    base_url=None,  # 可选：OpenAI 兼容网关
)
```

### `AnthropicModel`（Claude / Anthropic）

```python
from masfactory import AnthropicModel

model = AnthropicModel(
    model_name="claude-3-5-sonnet-latest",
    api_key="...",
    base_url=None,  # 可选
)
```

### `GeminiModel`（Google Gemini）

```python
from masfactory import GeminiModel

model = GeminiModel(
    model_name="gemini-2.0-flash",
    api_key="...",
    base_url=None,  # 可选
)
```

---

## 3) 自定义一个 Model 适配器

当你需要接入新的 provider、接入更严格的治理（审计、缓存、路由等），或统一企业内部网关时，可以自定义一个 `Model`。

### 3.1 `invoke()` 的接口约定

`Agent` 在 Think 阶段会调用：

- `invoke(messages: list[dict], tools: list[dict] | None, settings: dict | None = None, **kwargs) -> dict`

其中：

- `messages`：OpenAI 风格的对话消息列表（`role/content`），由 MASFactory 组装；
- `tools`：可选的工具 schema 列表（JSON Schema 形态），用于模型工具调用；
- `settings`：生成参数（如 temperature / top_p / max_tokens / stop 等），由适配器做校验与参数映射；
- `kwargs`：保留扩展位，用于 provider 特定参数（由适配器自行决定是否支持）。

返回值必须为**二选一**的结构化结果：

- 内容输出（CONTENT）：
  - `{"type": ModelResponseType.CONTENT, "content": "<text>"}`
- 工具调用（TOOL_CALL）：
  - `{"type": ModelResponseType.TOOL_CALL, "content": [{"id": "...", "name": "...", "arguments": {...}}, ...]}`

当返回 TOOL_CALL 时，MASFactory 会执行工具并继续向模型发起下一轮调用，直到拿到 CONTENT。

> 约束：重试、退避、限流等 provider 细节应封装在适配器内部，避免上层编排逻辑耦合 provider 行为。

### 3.2 最小骨架（推荐继承 `Model`）

推荐继承 `masfactory.adapters.model.Model`：它提供 settings 解析、统一的默认行为，并默认以 “shared” 作用域用于 `NodeTemplate`（避免被 deepcopy）。

```python
from masfactory.adapters.model import Model, ModelResponseType

class MyModel(Model):
    def __init__(self, model_name: str, api_key: str, base_url: str | None = None):
        super().__init__(model_name=model_name, invoke_settings=None)
        self._client = ...  # 初始化 provider client

    def invoke(self, messages: list[dict], tools: list[dict] | None, settings: dict | None = None, **kwargs) -> dict:
        # 1) 将 messages/tools/settings 映射为 provider 的请求
        # 2) 调用 provider，获得原始响应
        # 3) 归一化为 MASFactory 约定的结构化返回
        return {"type": ModelResponseType.CONTENT, "content": "..."}
```

建议在生产实现中补齐：

- request/response 日志与脱敏；
- 超时与重试策略；
- 错误分类（可重试/不可重试）；
- provider 速率限制与并发控制；
- `settings` 的校验与映射（如需支持 temperature/top_p/stop 等统一配置）。
