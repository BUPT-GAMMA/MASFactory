# 复合组件

复合组件是 MASFactory 内置的可复用预设子图，基于标准 `Graph` / `Loop` / `Agent` 组合实现，可直接在 `RootGraph` 中作为节点使用。

常见内置复合组件包括：

- `VerticalGraph`
- `VerticalDecisionGraph`
- `VerticalSolverFirstDecisionGraph`
- `HorizontalGraph`
- `AdjacencyMatrixGraph`
- `BrainstormingGraph`
- `HubGraph`
- `MeshGraph`
- `InstructorAssistantGraph`
- `PingPongGraph`

可直接从 `masfactory` 导入，并按普通图节点方式使用。


## 示例：嵌入 HorizontalGraph

`HorizontalGraph` 是一个内置的串行流水线：
`ENTRY -> node[0] -> node[1] -> ... -> EXIT`。

### 声明式

```python
from masfactory import CustomNode, HorizontalGraph, NodeTemplate, RootGraph

Pipeline = NodeTemplate(
    HorizontalGraph,
    node_args_list=[
        {"cls": CustomNode, "name": "a", "forward": lambda d: {"x": int(d["n"]) + 1}},
        {"cls": CustomNode, "name": "b", "forward": lambda d: {"y": int(d["x"]) * 2}},
    ],
    edge_keys_list=[{"x": "a 的输出"}],
)

g = RootGraph(
    name="composite_demo",
    nodes=[("pipeline", Pipeline)],
    edges=[
        ("entry", "pipeline", {"n": "输入数字"}),
        ("pipeline", "exit", {"y": "最终输出"}),
    ],
)

g.build()
out, _attrs = g.invoke({"n": 3})
print(out)  # {'y': 8}
```

### 命令式

```python
from masfactory import CustomNode, HorizontalGraph, RootGraph

g = RootGraph(name="composite_demo")

pipeline = g.create_node(
    HorizontalGraph,
    name="pipeline",
    node_args_list=[
        {"cls": CustomNode, "name": "a", "forward": lambda d: {"x": int(d["n"]) + 1}},
        {"cls": CustomNode, "name": "b", "forward": lambda d: {"y": int(d["x"]) * 2}},
    ],
    edge_keys_list=[{"x": "a 的输出"}],
)

g.edge_from_entry(pipeline, {"n": "输入数字"})
g.edge_to_exit(pipeline, {"y": "最终输出"})

g.build()
out, _attrs = g.invoke({"n": 3})
print(out)  # {'y': 8}
```
