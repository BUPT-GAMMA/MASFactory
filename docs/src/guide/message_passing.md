# Message Update and Passing (Horizontal / Vertical)

This page isolates one core topic: **how data moves in MASFactory**.  
We only distinguish two channels:

- **Horizontal passing**: data flows between nodes through `Edge` (`keys` decides what passes).
- **Vertical passing**: state is read/written through graph `attributes` (`pull_keys/push_keys` decides what is read/written).

---

## 0) One-page overview

<ThemedDiagram light="/imgs/message/overview-en-light.svg" dark="/imgs/message/overview-en-dark.svg" alt="Message passing overview" />

---

## 1) Horizontal passing: field routing on Edges

Rule: upstream node outputs a dict, and each edge routes selected fields via `keys`.

<ThemedDiagram light="/imgs/message/horizontal-en-light.svg" dark="/imgs/message/horizontal-en-dark.svg" alt="Horizontal message passing" />

### 1A) Declarative

```python
from masfactory import RootGraph, CustomNode

g = RootGraph(
    name="msg_horizontal_decl",
    nodes=[
        ("extract", CustomNode, lambda d: {"title": d["raw"].strip(), "len": len(d["raw"])}),
        ("render", CustomNode, lambda d: {"result": f"{d['title']} ({d['len']})"}),
    ],
    edges=[
        ("entry", "extract", {"raw": "raw text"}),
        ("extract", "render", {"title": "title", "len": "length"}),
        ("render", "exit", {"result": "final output"}),
    ],
)

g.build()
out, _ = g.invoke({"raw": "  hello masfactory  "})
print(out)  # {'result': 'hello masfactory (20)'}
```

### 1B) Imperative

```python
from masfactory import RootGraph, CustomNode

g = RootGraph(name="msg_horizontal_imp")

extract = g.create_node(
    CustomNode,
    name="extract",
    forward=lambda d: {"title": d["raw"].strip(), "len": len(d["raw"])},
)
render = g.create_node(
    CustomNode,
    name="render",
    forward=lambda d: {"result": f"{d['title']} ({d['len']})"},
)

g.edge_from_entry(extract, {"raw": "raw text"})
g.create_edge(extract, render, {"title": "title", "len": "length"})
g.edge_to_exit(render, {"result": "final output"})

g.build()
out, _ = g.invoke({"raw": "  hello masfactory  "})
print(out)  # {'result': 'hello masfactory (20)'}
```

---

## 2) Vertical passing: context read/write via attributes

Rule: nodes `pull` state from graph attributes, then `push` updated state back.

![vertical](/imgs/message/vertical.png)

### 2A) Declarative

```python
from masfactory import RootGraph, CustomNode, NodeTemplate

def step(d, attrs):
    next_counter = int(attrs.get("counter", 0)) + 1
    return {"payload": d["payload"], "counter": next_counter}

g = RootGraph(
    name="msg_vertical_decl",
    attributes={"counter": 0},
    nodes=[
        (
            "n1",
            NodeTemplate(CustomNode, forward=step, pull_keys={"counter": "shared counter"}, push_keys={"counter": "shared counter"}),
        ),
        (
            "n2",
            NodeTemplate(CustomNode, forward=step, pull_keys={"counter": "shared counter"}, push_keys={"counter": "shared counter"}),
        ),
    ],
    edges=[
        ("entry", "n1", {"payload": "business input"}),
        ("n1", "n2", {"payload": "pass-through"}),
        ("n2", "exit", {"payload": "final output", "counter": "accumulated count"}),
    ],
)

g.build()
out, attrs = g.invoke({"payload": "ok"})
print(out)    # {'payload': 'ok', 'counter': 2}
print(attrs)  # {'counter': 2}
```

### 2B) Imperative

```python
from masfactory import RootGraph, CustomNode

def step(d, attrs):
    next_counter = int(attrs.get("counter", 0)) + 1
    return {"payload": d["payload"], "counter": next_counter}

g = RootGraph(name="msg_vertical_imp", attributes={"counter": 0})

n1 = g.create_node(
    CustomNode,
    name="n1",
    forward=step,
    pull_keys={"counter": "shared counter"},
    push_keys={"counter": "shared counter"},
)
n2 = g.create_node(
    CustomNode,
    name="n2",
    forward=step,
    pull_keys={"counter": "shared counter"},
    push_keys={"counter": "shared counter"},
)

g.edge_from_entry(n1, {"payload": "business input"})
g.create_edge(n1, n2, {"payload": "pass-through"})
g.edge_to_exit(n2, {"payload": "final output", "counter": "accumulated count"})

g.build()
out, attrs = g.invoke({"payload": "ok"})
print(out)    # {'payload': 'ok', 'counter': 2}
print(attrs)  # {'counter': 2}
```
