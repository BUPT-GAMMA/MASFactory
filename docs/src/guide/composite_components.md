# Composite Components

Composite components are reusable, prebuilt subgraphs in MASFactory. They are implemented with standard `Graph`/`Loop`/`Agent` primitives, and can be created directly as nodes inside your `RootGraph`.

Common built-in composite components include:

- `VerticalGraph`
- `VerticalDecisionGraph`
- `VerticalSolverFirstDecisionGraph`
- `HorizontalGraph`
- `AdjacencyListGraph`
- `AdjacencyMatrixGraph`
- `BrainstormingGraph`
- `HubGraph`
- `MeshGraph`
- `InstructorAssistantGraph`
- `PingPongGraph`

Import them from `masfactory` directly and use them like any other graph node.

Most composite components take keyword-style configuration. In declarative graphs, use `NodeTemplate(...)`
to pass those kwargs.

---

## Minimal example: embed a HorizontalGraph

`HorizontalGraph` is a prebuilt sequential pipeline:
`ENTRY -> node[0] -> node[1] -> ... -> EXIT`.

### Declarative (recommended)

```python
from masfactory import CustomNode, HorizontalGraph, NodeTemplate, RootGraph

Pipeline = NodeTemplate(
    HorizontalGraph,
    node_args_list=[
        {"cls": CustomNode, "name": "a", "forward": lambda d: {"x": int(d["n"]) + 1}},
        {"cls": CustomNode, "name": "b", "forward": lambda d: {"y": int(d["x"]) * 2}},
    ],
    edge_keys_list=[{"x": "a output"}],
)

g = RootGraph(
    name="composite_demo",
    nodes=[("pipeline", Pipeline)],
    edges=[
        ("entry", "pipeline", {"n": "input number"}),
        ("pipeline", "exit", {"y": "final output"}),
    ],
)

g.build()
out, _attrs = g.invoke({"n": 3})
print(out)  # {'y': 8}
```

### Imperative (alternative)

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
    edge_keys_list=[{"x": "a output"}],
)

g.edge_from_entry(pipeline, {"n": "input number"})
g.edge_to_exit(pipeline, {"y": "final output"})

g.build()
out, _attrs = g.invoke({"n": 3})
print(out)  # {'y': 8}
```
