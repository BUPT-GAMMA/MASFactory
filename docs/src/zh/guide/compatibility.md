# 工作流兼容层

MASFactory 可以导入 **Dify**、**ChatDev** 和 **Langflow** 的工作流文件，并把它们作为 MASFactory 图运行。当你已经在其他产品里设计了工作流，希望在 MASFactory 中查看、复用或逐步迁移它时，可以使用这个兼容层。

本页只介绍日常使用方式。函数签名和更底层的扩展点见 [`API 文档`](/zh/api_reference#工作流兼容层)。

---

## 可以导入什么

| 来源 | 常见文件 | 使用 API |
|------|----------|----------|
| Dify workflow app | `.yml` / `.yaml` | `load_graph_from_dify_yaml()` |
| Python 中已经加载好的 Dify mapping | `dict` | `load_graph_from_dify_dict()` |
| ChatDev workflow 或 chain config | `.yml` / `.yaml` | `load_graph_from_chatdev_yaml()` |
| Langflow export | `.json` | `load_graph_from_langflow_json()` |

导入结果是一个 MASFactory 图。你可以像使用普通 MASFactory 图一样调用 `build()` 和 `invoke()`。

---

## 导入并运行

### Dify

```python
from masfactory.compatibility import load_graph_from_dify_yaml

graph = load_graph_from_dify_yaml("workflow.yml")
graph.build()

result, attributes = graph.invoke({"query": "hello"})
print(result)
```

Dify 导入会尽量保留常见 workflow 行为，包括 start/end 节点、answer 节点、LLM 节点、code 节点、条件分支、变量赋值、变量聚合、HTTP 请求、工具、知识检索、iteration 和 loop。

如果 Dify 工作流包含 LLM 节点，可以通过 `DifyCompileOptions` 传入模型凭据或自定义模型工厂：

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

做离线检查时，可以使用 stub 响应：

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

ChatDev 导入支持 agent 类节点、literal 节点、loop counter、majority voting、条件路由和循环区域。如果只想预览拓扑，可以设置 `use_placeholder=True`：

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

Langflow 导入更适合由 ChatInput、Prompt、LLM、ChatOutput 这类组件组成的聊天流。其他组件可能会以透传节点表示。

---

## 导出 AML 或旧拓扑预览

每个 loader 都可以额外写出一个 AML 文档，用于 Visualizer 预览、编辑和迁移检查：

```python
from masfactory.compatibility import load_graph_from_langflow_json

graph = load_graph_from_langflow_json(
    "flow.json",
    aml_path=True,
)
```

当 `aml_path=True` 时，MASFactory 会把 AML 文档写到：

```text
masfactory/compatibility/out/
```

也可以指定输出文件名：

```python
graph = load_graph_from_dify_yaml(
    "workflow.yml",
    aml_path="my_dify_preview.aml",
)
```

相对路径会解析到 `masfactory/compatibility/out/` 下；绝对路径会按原样使用。

导出的 AML 用于 Visualizer 拓扑预览和源级检查。真正执行时，应以导入得到的 graph 为准。

如果仍然需要旧 Visualizer graph-design 预览格式，可以传入 `graph_design_path=True` 或 `.json` 路径。该导出保留用于 legacy 工具，但新 MASFactory 工作流的主交换格式是 AML。

---

## 常用选项

### 设置图名称

```python
graph = load_graph_from_langflow_json(
    "flow.json",
    graph_name="customer_support_flow",
)
```

### 传入内联内容

loader 可以接收文件路径、bytes 或内联文档文本：

```python
from pathlib import Path

yaml_text = Path("workflow.yml").read_text(encoding="utf-8")
graph = load_graph_from_dify_yaml(yaml_text)
```

对于很大的导出文件，建议传入 `Path` 或 `bytes`。

### 使用 Stub Model

当你只想验证图结构、不想发起模型调用时，可以使用 stub model：

```python
from masfactory.compatibility import ChatDevCompileOptions

options = ChatDevCompileOptions(
    use_stub_llm=True,
    llm_stub_text="preview response",
)
```

ChatDev 和 Langflow 的 compile options 默认使用 stub LLM。Dify 默认会尝试解析真实模型，除非显式设置 `use_stub_llm=True`。

---

## 什么时候使用

适合使用兼容层导入的场景：

- 想把已有外部工作流放到 MASFactory 中运行；
- 想在 MASFactory Visualizer 中查看外部工作流结构；
- 正在迁移工作流，需要一个可运行的起点；
- 希望先桥接外部节点，再逐步替换成原生 MASFactory 节点。

如果是新的 MASFactory 原生项目，优先直接使用 MASFactory 组件或 `VibeGraphing` 构建。

---

## 当前限制

- 兼容层导入是 best-effort，导入后的图不保证和原产品运行时完全一致。
- Dify 主要覆盖常见 workflow 节点；工具、HTTP、知识检索等外部服务如果需要真实行为，需要接入对应运行时 hook。
- ChatDev 和 Langflow 的复杂组件可能会以透传节点或 stub model 调用运行。
- `aml_path` 导出用于源级预览和迁移检查；导入得到的 graph 仍然是执行语义的来源。
- `graph_design_path` 导出是旧结构预览格式，不应作为新 MASFactory 工作流的主要编辑格式。
