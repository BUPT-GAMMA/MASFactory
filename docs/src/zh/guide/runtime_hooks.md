# 运行时 Hooks

本章介绍 MASFactory 的 **运行时 Hooks**（钩子）机制：你可以在不修改业务逻辑的前提下，为节点/边注册回调函数，用于记录日志、采集指标、追踪消息流、对接可观测与调试工具等。

源码参考：`masfactory/utils/hook.py`、`masfactory/core/node.py`、`masfactory/core/edge.py`、`masfactory/components/graphs/base_graph.py`

<ThemedDiagram
  light="/imgs/hooks/node-lifecycle-light.svg"
  dark="/imgs/hooks/node-lifecycle-dark.svg"
  alt="节点生命周期与 Hooks 切入点"
/>

---

## 1) Hooks 是什么

MASFactory 的 hooks 是一个**轻量、同步、进程内**的事件机制：

- **轻量**：不依赖外部中间件；本质上就是在关键调用点 `dispatch(...)` 一组回调。
- **同步**：hook 回调与运行时同线程执行；回调抛出的异常会中断执行（因此建议回调内部自行兜底）。
- **进程内**：适合日志/指标/调试信息采集；如需跨进程通信，请在 hook 内部自行转发（例如 WebSocket/HTTP）。

---

## 2) 可用的 Hook 点（节点 + 边）

### 2.1 Node 的 HookStage（BEFORE / AFTER / ERROR）

`Node.Hook.*` 是一组 `HookStage`，每个 stage 都有三类切入点：

- `*.BEFORE`：函数调用前触发
- `*.AFTER`：函数返回后触发（会携带返回值）
- `*.ERROR`：函数抛异常时触发（会携带异常对象）

常用的 stage：

- `Node.Hook.BUILD`：`build()` 期间
- `Node.Hook.EXECUTE`：`execute()` 期间（一次节点调度的总入口）
- `Node.Hook.MESSAGE_AGGREGATE_IN`：聚合入边消息（`_message_aggregate_in()`）
- `Node.Hook.FORWARD`：核心计算（`_forward(input)`）
- `Node.Hook.MESSAGE_DISPATCH_OUT`：向出边分发消息（`_message_dispatch_out(output)`）

> 注意  
> `EXECUTE` 钩子总是存在，因为 `Node.execute()` 在基类中已被装饰。  
> `FORWARD` 钩子是否生效取决于具体实现是否使用了 `@masf_hook(Node.Hook.FORWARD)`（MASFactory 内置组件已覆盖；自定义节点建议显式加上）。

### 2.2 Edge 的事件 Hooks（SEND / RECEIVE）

Edge 提供两个事件点（不是 HookStage，因此没有 BEFORE/AFTER/ERROR 三段）：

- `Edge.Hook.SEND_MESSAGE`：`send_message(...)` 发送后触发
- `Edge.Hook.RECEIVE_MESSAGE`：`receive_message()` 取走消息时触发

适合用于：记录消息流向、做消息审计、做链路追踪等。

---

## 3) 如何注册 Hook

### 3.1 注册到单个 Node

```python
from masfactory.core.node import Node

def before_forward(node: Node, input: dict):
    print(f"[{node.name}] input keys: {list(input.keys())}")

def after_forward(node: Node, output: dict, input: dict):
    print(f"[{node.name}] output keys: {list(output.keys())}")

node.hook_register(Node.Hook.FORWARD.BEFORE, before_forward)
node.hook_register(Node.Hook.FORWARD.AFTER, after_forward)
```

### 3.2 递归注册到整张 Graph（推荐）

对图递归注册更常用，便于“一次配置，全局生效”：

```python
from masfactory.core.node import Node
from masfactory.components.graphs.root_graph import RootGraph

def trace_execute(node: Node, outer_env: dict | None):
    print(f"[EXECUTE] {node.name}")

graph = RootGraph("demo")
graph.hook_register(Node.Hook.EXECUTE.BEFORE, trace_execute, recursion=True)
```

### 3.3 选择器过滤（target_type / target_names / target_filter）

`hook_register(...)` 支持选择性挂载（只对某类节点或某些名字生效）：

```python
from masfactory.components.agents.agent import Agent
from masfactory.core.node import Node

def only_agents(node: Node, input: dict):
    print(f"[AGENT] {node.name}")

graph.hook_register(
    Node.Hook.FORWARD.BEFORE,
    only_agents,
    recursion=True,
    target_type=Agent,
)
```

---

## 4) 回调函数签名（重要）

MASFactory 的 `HookStage` 会向回调传入固定的参数顺序：

- `BEFORE`：`(self, *original_args, **original_kwargs)`
- `AFTER`：`(self, result, *original_args, **original_kwargs)`
- `ERROR`：`(self, err, *original_args, **original_kwargs)`

举例：`Node._forward(self, input)` 的 AFTER 回调签名应为：

```python
def after_forward(node, output, input):
    ...
```

---

## 5) 示例：追踪消息流（Edge Hooks）

```python
from masfactory.core.edge import Edge
from masfactory.core.node import Node

def on_send(sender: Node, receiver: Node, message: dict):
    print(f"{sender.name} -> {receiver.name}: {list(message.keys())}")

graph.hook_register(Edge.Hook.SEND_MESSAGE, on_send, recursion=True)
```

---

## 6) 自定义节点：如何让 FORWARD hooks 生效

如果你实现自定义节点，并希望 `Node.Hook.FORWARD.*` 可用，建议在 `_forward` 上显式加装饰器：

```python
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook

class MyNode(Node):
    @masf_hook(Node.Hook.FORWARD)
    def _forward(self, input: dict) -> dict:
        return {"ok": True}
```

这样你对 `Node.Hook.FORWARD.BEFORE/AFTER/ERROR` 的注册才会在该节点上触发。

