# Loop Example

This example demonstrates how to use the `Loop` component in MASFactory to implement a code review and iterative fixing workflow. This is a typical scenario that requires loop processing: code quality improvement usually requires multiple rounds of "review → fix → re-review" iteration until quality standards are met.

## Message Passing View

- **Horizontal (Edge keys):** loop body fields flow on `controller -> ... -> controller`
- **Vertical (attributes):** this example stores `run_result` in attributes for termination decision

## Diagram
![Diagram](/imgs/examples/loop.png)

## Example Code

A minimal offline loop: increment `count` until `count >= 3`.

### Declarative (recommended)

```python
from masfactory import CustomNode, Loop, NodeTemplate, RootGraph


def terminate_cond(message: dict, _attrs: dict) -> bool:
    return int(message.get("count", 0)) >= 3


LoopT = NodeTemplate(
    Loop,
    max_iterations=50,
    terminate_condition_function=terminate_cond,
    nodes=[
        ("step", CustomNode, lambda d: {"count": int(d["count"]) + 1}),
    ],
    edges=[
        ("controller", "step", {"count": "count"}),
        ("step", "controller", {"count": "count"}),
    ],
)

g = RootGraph(
    name="loop_demo",
    nodes=[("loop", LoopT)],
    edges=[
        ("entry", "loop", {"count": "initial count"}),
        ("loop", "exit", {"count": "final count"}),
    ],
)

g.build()
out, _attrs = g.invoke({"count": 0})
print(out)  # {'count': 3}
```

### Imperative (alternative)

```python
from masfactory import CustomNode, Loop, RootGraph


def terminate_cond(message: dict, _attrs: dict) -> bool:
    return int(message.get("count", 0)) >= 3


g = RootGraph(name="loop_demo")

loop = g.create_node(
    Loop,
    name="loop",
    max_iterations=50,
    terminate_condition_function=terminate_cond,
)

step = loop.create_node(CustomNode, name="step", forward=lambda d: {"count": int(d["count"]) + 1})
loop.edge_from_controller(step, {"count": "count"})
loop.edge_to_controller(step, {"count": "count"})

g.edge_from_entry(loop, {"count": "initial count"})
g.edge_to_exit(loop, {"count": "final count"})

g.build()
out, _attrs = g.invoke({"count": 0})
print(out)  # {'count': 3}
```

::: tip Core Features of Loop Component
- `max_iterations`: Set maximum number of iterations to prevent infinite loops
- `edge_from_controller`: Pass data from loop controller to nodes inside the loop
- `edge_to_controller`: Return data from nodes inside the loop to the controller
- The loop will automatically terminate when maximum iterations are reached or stop condition is met
:::
