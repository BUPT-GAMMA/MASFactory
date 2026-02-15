# Runtime Hooks

This page explains MASFactory **runtime hooks**: lightweight, in-process callbacks that you can attach to nodes/edges for logging, metrics, tracing message flows, and integrating with observability/debug tooling—without changing business logic.

Source references: `masfactory/utils/hook.py`, `masfactory/core/node.py`, `masfactory/core/edge.py`, `masfactory/components/graphs/base_graph.py`

<ThemedDiagram
  light="/imgs/hooks/node-lifecycle-light.svg"
  dark="/imgs/hooks/node-lifecycle-dark.svg"
  alt="Node lifecycle and hook stages"
/>

---

## 1) What hooks are

MASFactory hooks are **lightweight, synchronous, in-process** events:

- **Lightweight**: no external middleware—just `dispatch(...)` at key call sites.
- **Synchronous**: callbacks run in the same thread; exceptions from hooks will interrupt execution (so make hooks defensive).
- **In-process**: ideal for logs/metrics/debug traces; cross-process communication is possible but must be done inside the hook (WebSocket/HTTP/etc.).

---

## 2) Available hook points (Node + Edge)

### 2.1 Node HookStage (BEFORE / AFTER / ERROR)

`Node.Hook.*` are `HookStage`s. Each stage provides:

- `*.BEFORE`: fired before the call
- `*.AFTER`: fired after return (includes the return value)
- `*.ERROR`: fired on exception (includes the error)

Common stages:

- `Node.Hook.BUILD`: during `build()`
- `Node.Hook.EXECUTE`: during `execute()` (the overall scheduling entry)
- `Node.Hook.MESSAGE_AGGREGATE_IN`: `_message_aggregate_in()`
- `Node.Hook.FORWARD`: `_forward(input)` (core computation)
- `Node.Hook.MESSAGE_DISPATCH_OUT`: `_message_dispatch_out(output)`

> Note  
> `EXECUTE` hooks always exist because `Node.execute()` is decorated in the base class.  
> `FORWARD` hooks only fire if the implementation uses `@masf_hook(Node.Hook.FORWARD)` (built-in components do; custom nodes should add it explicitly).

### 2.2 Edge event hooks (SEND / RECEIVE)

Edges expose two event points (not HookStage, so no BEFORE/AFTER/ERROR split):

- `Edge.Hook.SEND_MESSAGE`: fired after `send_message(...)`
- `Edge.Hook.RECEIVE_MESSAGE`: fired when `receive_message()` consumes the buffered message

Typical uses: message tracing, auditing, distributed correlation, etc.

---

## 3) Registering hooks

### 3.1 Register on a single node

```python
from masfactory.core.node import Node

def before_forward(node: Node, input: dict):
    print(f"[{node.name}] input keys: {list(input.keys())}")

def after_forward(node: Node, output: dict, input: dict):
    print(f"[{node.name}] output keys: {list(output.keys())}")

node.hook_register(Node.Hook.FORWARD.BEFORE, before_forward)
node.hook_register(Node.Hook.FORWARD.AFTER, after_forward)
```

### 3.2 Register recursively on a whole graph (recommended)

```python
from masfactory.core.node import Node
from masfactory.components.graphs.root_graph import RootGraph

def trace_execute(node: Node, outer_env: dict | None):
    print(f"[EXECUTE] {node.name}")

graph = RootGraph("demo")
graph.hook_register(Node.Hook.EXECUTE.BEFORE, trace_execute, recursion=True)
```

### 3.3 Filter by selector (target_type / target_names / target_filter)

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

## 4) Callback signatures (important)

HookStage dispatches arguments in a fixed order:

- `BEFORE`: `(self, *original_args, **original_kwargs)`
- `AFTER`: `(self, result, *original_args, **original_kwargs)`
- `ERROR`: `(self, err, *original_args, **original_kwargs)`

Example: for `Node._forward(self, input)`, the AFTER hook signature should be:

```python
def after_forward(node, output, input):
    ...
```

---

## 5) Example: tracing message flow (Edge hooks)

```python
from masfactory.core.edge import Edge
from masfactory.core.node import Node

def on_send(sender: Node, receiver: Node, message: dict):
    print(f"{sender.name} -> {receiver.name}: {list(message.keys())}")

graph.hook_register(Edge.Hook.SEND_MESSAGE, on_send, recursion=True)
```

---

## 6) Custom nodes: enabling FORWARD hooks

If you implement a custom node and want `Node.Hook.FORWARD.*` hooks to fire, decorate `_forward` explicitly:

```python
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook

class MyNode(Node):
    @masf_hook(Node.Hook.FORWARD)
    def _forward(self, input: dict) -> dict:
        return {"ok": True}
```

