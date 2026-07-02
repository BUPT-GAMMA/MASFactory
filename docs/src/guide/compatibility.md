# Workflow Compatibility

MASFactory can import workflow files from **Dify**, **ChatDev**, and **Langflow** and run them as MASFactory graphs. Use this when you already have a workflow designed in another product and want to inspect, reuse, or gradually port it into MASFactory.

This page focuses on day-to-day usage. For function signatures and lower-level extension points, see [`API Reference`](/api_reference#workflow-compatibility).

---

## What You Can Import

| Source | Typical file | Use this API |
|--------|--------------|--------------|
| Dify workflow app | `.yml` / `.yaml` | `load_graph_from_dify_yaml()` |
| Dify mapping already loaded in Python | `dict` | `load_graph_from_dify_dict()` |
| ChatDev workflow or chain config | `.yml` / `.yaml` | `load_graph_from_chatdev_yaml()` |
| Langflow export | `.json` | `load_graph_from_langflow_json()` |

The import result is a MASFactory graph. You call `build()` and `invoke()` the same way you would with a graph you created directly in Python.

---

## Import And Run

### Dify

```python
from masfactory.compatibility import load_graph_from_dify_yaml

graph = load_graph_from_dify_yaml("workflow.yml")
graph.build()

result, attributes = graph.invoke({"query": "hello"})
print(result)
```

Dify imports try to preserve common workflow behavior such as start/end nodes, answer nodes, LLM nodes, code nodes, conditions, variable assignment, aggregation, HTTP requests, tools, knowledge retrieval, iterations, and loops.

If your Dify workflow contains LLM nodes, pass model credentials or a custom model factory through `DifyCompileOptions`:

```python
from masfactory.compatibility import DifyCompileOptions, load_graph_from_dify_yaml

graph = load_graph_from_dify_yaml(
    "workflow.yml",
    options=DifyCompileOptions(
        openai_api_key="...",
        openai_base_url="...",
    ),
)
```

For offline checks, use a stub response:

```python
graph = load_graph_from_dify_yaml(
    "workflow.yml",
    options=DifyCompileOptions(use_stub_llm=True),
)
```

### ChatDev

```python
from masfactory.compatibility import ChatDevCompileOptions, load_graph_from_chatdev_yaml

graph = load_graph_from_chatdev_yaml(
    "chatdev_workflow.yaml",
    options=ChatDevCompileOptions(use_stub_llm=True),
)
graph.build()

result, attributes = graph.invoke({"task": "Draft a short project plan"})
print(result)
```

ChatDev imports support agent-like nodes, literal nodes, loop counters, majority voting, conditional routing, and loop regions. For topology-only previews, set `use_placeholder=True`:

```python
graph = load_graph_from_chatdev_yaml(
    "chatdev_workflow.yaml",
    use_placeholder=True,
)
```

### Langflow

```python
from masfactory.compatibility import LangflowCompileOptions, load_graph_from_langflow_json

graph = load_graph_from_langflow_json(
    "flow.json",
    options=LangflowCompileOptions(use_stub_llm=True),
)
graph.build()

result, attributes = graph.invoke({"input": "hello"})
print(result)
```

Langflow imports are most useful for chat-style flows built from ChatInput, Prompt, LLM, and ChatOutput-style components. Other components may be represented as passthrough nodes.

---

## Export AML Or Legacy Topology Previews

Every loader can also write an AML document for Visualizer preview, editing, and migration review:

```python
from masfactory.compatibility import load_graph_from_langflow_json

graph = load_graph_from_langflow_json(
    "flow.json",
    aml_path=True,
)
```

When `aml_path=True`, MASFactory writes the AML document under:

```text
masfactory/compatibility/out/
```

You can also choose the output name:

```python
graph = load_graph_from_dify_yaml(
    "workflow.yml",
    aml_path="my_dify_preview.aml",
)
```

Relative paths are resolved under `masfactory/compatibility/out/`; absolute paths are used as-is.

The exported AML is for Visualizer topology preview and source-level inspection. Treat the imported graph itself as the executable artifact.

If you still need the old Visualizer graph-design preview format, pass `graph_design_path=True` or a `.json` path. That export remains available for legacy tooling, but AML is the primary interchange format.

---

## Common Options

### Set A Graph Name

```python
graph = load_graph_from_langflow_json(
    "flow.json",
    graph_name="customer_support_flow",
)
```

### Pass Inline Content

Loaders accept file paths, bytes, or inline document text:

```python
from pathlib import Path

yaml_text = Path("workflow.yml").read_text(encoding="utf-8")
graph = load_graph_from_dify_yaml(yaml_text)
```

For very large exports, prefer passing a `Path` or `bytes` object.

### Use Stub Models

Stub models are useful when you want to verify graph structure without making model calls:

```python
from masfactory.compatibility import ChatDevCompileOptions

options = ChatDevCompileOptions(
    use_stub_llm=True,
    llm_stub_text="preview response",
)
```

ChatDev and Langflow compile options default to stub LLM behavior. Dify defaults to real model resolution unless `use_stub_llm=True` is set.

---

## When To Use This Feature

Use compatibility imports when:

- you want to run an existing external workflow inside MASFactory;
- you want to inspect an external workflow in MASFactory Visualizer;
- you are migrating a workflow and want a runnable starting point;
- you need a bridge while gradually replacing external nodes with native MASFactory nodes.

For new MASFactory-native projects, prefer building directly with MASFactory components or `VibeGraphing`.

---

## Current Limits

- Compatibility imports are best-effort. Imported graphs may not behave exactly like the original product runtime.
- Dify coverage focuses on common workflow nodes. External services such as tools, HTTP, and knowledge retrieval need runtime hooks when real behavior is required.
- ChatDev and Langflow complex components may run as passthrough nodes or stub model calls.
- `aml_path` export is for source-level preview and migration review; the imported graph remains the execution source of truth.
- `graph_design_path` export is a legacy structure preview and should not be treated as the main authoring format for new MASFactory workflows.
