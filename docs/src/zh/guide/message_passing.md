# 消息更新与传递（水平 / 垂直）

这页把 MASFactory 里的“数据怎么流动”单独拆开讲清楚。  
我们只区分两类传递：

- **水平消息传递**：沿着 `Edge` 在节点之间流动（`keys` 决定传什么）。
- **垂直消息传递**：通过 `attributes` 在图上下文中读写（`pull_keys/push_keys` 决定读写什么）。

---

## 0) 一图总览

<ThemedDiagram light="/imgs/message/overview-light.svg" dark="/imgs/message/overview-dark.svg" alt="消息传递总览：水平与垂直" />

---

## 1) 水平消息传递：基于 Edge 的字段传参

规则：上游节点产出一个字典，边根据 `keys` 把字段路由给下游节点。

<ThemedDiagram light="/imgs/message/horizontal-light.svg" dark="/imgs/message/horizontal-dark.svg" alt="水平消息传递示意图" />

### 1A) 声明式

```python
from masfactory import RootGraph, CustomNode

g = RootGraph(
    name="msg_horizontal_decl",
    nodes=[
        ("extract", CustomNode, lambda d: {"title": d["raw"].strip(), "len": len(d["raw"])}),
        ("render", CustomNode, lambda d: {"result": f"{d['title']} ({d['len']})"}),
    ],
    edges=[
        ("entry", "extract", {"raw": "原始文本"}),
        ("extract", "render", {"title": "标题", "len": "长度"}),
        ("render", "exit", {"result": "最终输出"}),
    ],
)

g.build()
out, _ = g.invoke({"raw": "  hello masfactory  "})
print(out)  # {'result': 'hello masfactory (20)'}
```

### 1B) 命令式

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

g.edge_from_entry(extract, {"raw": "原始文本"})
g.create_edge(extract, render, {"title": "标题", "len": "长度"})
g.edge_to_exit(render, {"result": "最终输出"})

g.build()
out, _ = g.invoke({"raw": "  hello masfactory  "})
print(out)  # {'result': 'hello masfactory (20)'}
```

---

## 2) 垂直消息传递：基于 attributes 的上下文读写

规则：节点从图上下文 `pull` 变量，执行后把结果 `push` 回图上下文。

![vertical](/imgs/message/vertical.png)

### 2A) 声明式

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
            NodeTemplate(CustomNode, forward=step, pull_keys={"counter": "共享计数"}, push_keys={"counter": "共享计数"}),
        ),
        (
            "n2",
            NodeTemplate(CustomNode, forward=step, pull_keys={"counter": "共享计数"}, push_keys={"counter": "共享计数"}),
        ),
    ],
    edges=[
        ("entry", "n1", {"payload": "业务输入"}),
        ("n1", "n2", {"payload": "透传"}),
        ("n2", "exit", {"payload": "最终输出", "counter": "累计次数"}),
    ],
)

g.build()
out, attrs = g.invoke({"payload": "ok"})
print(out)    # {'payload': 'ok', 'counter': 2}
print(attrs)  # {'counter': 2}
```

### 2B) 命令式

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
    pull_keys={"counter": "共享计数"},
    push_keys={"counter": "共享计数"},
)
n2 = g.create_node(
    CustomNode,
    name="n2",
    forward=step,
    pull_keys={"counter": "共享计数"},
    push_keys={"counter": "共享计数"},
)

g.edge_from_entry(n1, {"payload": "业务输入"})
g.create_edge(n1, n2, {"payload": "透传"})
g.edge_to_exit(n2, {"payload": "最终输出", "counter": "累计次数"})

g.build()
out, attrs = g.invoke({"payload": "ok"})
print(out)    # {'payload': 'ok', 'counter': 2}
print(attrs)  # {'counter': 2}
```
