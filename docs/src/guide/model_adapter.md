# Model Adapters (Model)

MASFactory uses **model adapters** to hide differences across LLM providers and expose a stable, testable contract for `Agent`. With the same orchestration code, you can switch between OpenAI-compatible endpoints, Anthropic, Gemini, and other implementations.

---

## Source of truth (code)

- `Model` interface and built-in implementations: `masfactory/adapters/model.py`

---

## 1) How to use a Model (minimal example)

A model adapter is one of the constructor arguments of `Agent`. You only need to create a `Model` instance and pass it into `Agent` (or reuse it via `NodeTemplate`).

The example below builds a minimal two-stage agent workflow:

`ENTRY → analyze → answer → EXIT`

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
        ("analyze", BaseAgent(instructions="You analyze the question.", prompt_template="User question: {query}")),
        ("answer", BaseAgent(instructions="You provide the final answer.", prompt_template="Question: {query}\nAnalysis: {analysis}")),
    ],
    edges=[
        ("entry", "analyze", {"query": "User question"}),
        ("analyze", "answer", {"query": "Original question", "analysis": "Analysis result"}),
        ("answer", "exit", {"answer": "Final answer"}),
    ],
)

g.build()
out, _attrs = g.invoke({"query": "I want to learn Python. Where should I start?"})
print(out["answer"])
```

---

## 2) Built-in model adapters (ready to use)

MASFactory currently ships the following adapters (all importable from `masfactory`):

### `OpenAIModel` (OpenAI-compatible endpoints)

```python
from masfactory import OpenAIModel

model = OpenAIModel(
    model_name="gpt-4o-mini",
    api_key="...",
    base_url=None,  # optional: OpenAI-compatible gateway
)
```

### `AnthropicModel` (Claude / Anthropic)

```python
from masfactory import AnthropicModel

model = AnthropicModel(
    model_name="claude-3-5-sonnet-latest",
    api_key="...",
    base_url=None,  # optional
)
```

### `GeminiModel` (Google Gemini)

```python
from masfactory import GeminiModel

model = GeminiModel(
    model_name="gemini-2.0-flash",
    api_key="...",
    base_url=None,  # optional
)
```

---

## 3) Implement a custom Model adapter

You may want a custom adapter when integrating a new provider, applying stricter governance (auditing, caching, routing), or standardizing access through an internal gateway.

### 3.1 The `invoke()` contract

During Think, `Agent` calls:

- `invoke(messages: list[dict], tools: list[dict] | None, settings: dict | None = None, **kwargs) -> dict`

Where:

- `messages`: OpenAI-style chat messages (`role/content`), assembled by MASFactory
- `tools`: optional tool schemas (JSON Schema) for tool calling
- `settings`: generation settings (temperature / top_p / max_tokens / stop, etc.), validated and mapped by the adapter
- `kwargs`: an extension slot for provider-specific parameters (adapter-defined)

Return value must be one of the following normalized results:

- Content output (CONTENT):
  - `{"type": ModelResponseType.CONTENT, "content": "<text>"}`
- Tool calls (TOOL_CALL):
  - `{"type": ModelResponseType.TOOL_CALL, "content": [{"id": "...", "name": "...", "arguments": {...}}, ...]}`

When TOOL_CALL is returned, MASFactory executes the tools and continues calling the model until a final CONTENT response is produced.

> Constraint: retries/backoff/rate limiting should be encapsulated inside the adapter, so orchestration logic does not depend on provider behavior.

### 3.2 Minimal skeleton (recommended: inherit `Model`)

It is recommended to inherit `masfactory.adapters.model.Model`: it provides shared settings parsing and default behaviors, and it is marked as “shared” for `NodeTemplate` by default (to avoid unintended deepcopy).

```python
from masfactory.adapters.model import Model, ModelResponseType

class MyModel(Model):
    def __init__(self, model_name: str, api_key: str, base_url: str | None = None):
        super().__init__(model_name=model_name, invoke_settings=None)
        self._client = ...  # initialize provider client

    def invoke(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        settings: dict | None = None,
        **kwargs,
    ) -> dict:
        # 1) map messages/tools/settings to provider request
        # 2) call provider and obtain raw response
        # 3) normalize to MASFactory contract
        return {"type": ModelResponseType.CONTENT, "content": "..."}
```

For production-grade adapters, consider adding:

- request/response logging with redaction
- timeouts and retry strategies
- error classification (retryable vs fatal)
- rate limiting and concurrency control
- strict validation/mapping for `settings` (temperature/top_p/stop, etc.)

