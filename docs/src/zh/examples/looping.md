# 循环（Loop）

`Loop` 用来表达“反复迭代直到满足条件”的控制流（类似 `while`）。它是 MASFactory 里唯一允许环状结构的组件（通过内部 `Controller` 实现）。

## 消息传递视角

- **水平（Edge keys）**：循环体每轮通过 `controller -> step -> controller` 传递 `count`
- **垂直（attributes）**：可用于保存循环轮次、外部状态、调试标记；本示例重点是水平回环

## 示例：计数器循环（离线可跑）

每轮把 `count += 1`，当 `count >= 3` 时退出循环。

## 示意图
![示意图](/imgs/examples/loop.png)

## 示例代码（声明式，推荐）

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
        # controller -> step：开始一轮
        ("controller", "step", {"count": "count"}),
        # step -> controller：回到 controller，触发下一轮/终止判断
        ("step", "controller", {"count": "count"}),
    ],
)

g = RootGraph(
    name="loop_demo",
    nodes=[("loop", LoopT)],
    edges=[
        ("entry", "loop", {"count": "初始计数"}),
        ("loop", "exit", {"count": "最终计数"}),
    ],
)

g.build()
out, _attrs = g.invoke({"count": 0})
print(out)  # {'count': 3}
```

::: tip 关键点
- Loop 内部有 `controller`（控制器）与 `terminate`（提前退出）两个特殊结点。
- 声明式 `edges` 支持把 `controller` 写成 `"controller"`（或 `"entry"`）别名。
:::

## 示例代码（命令式，备选）

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

g.edge_from_entry(loop, {"count": "初始计数"})
g.edge_to_exit(loop, {"count": "最终计数"})

g.build()
out, _attrs = g.invoke({"count": 0})
print(out)  # {'count': 3}
```
