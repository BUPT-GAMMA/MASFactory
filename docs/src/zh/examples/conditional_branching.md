# 条件分支（LogicSwitch / AgentSwitch）

MASFactory 提供两类常用分支组件：

- `LogicSwitch`：用 **Python 条件函数**做路由（可离线运行）
- `AgentSwitch`：用 **LLM 语义判断**做路由（需要模型）

## 消息传递视角

- **水平（Edge keys）**：上游字段先传给 `router`，再按分支边传给目标节点
- **垂直（attributes）**：分支条件函数可读取 attributes；本页示例主要走水平字段

## 示意图
![示意图](/imgs/examples/conditional_branching_logic.png)

---

## 1) LogicSwitch：基于规则的路由（离线可跑）

示例：先用 `scorer` 计算分数，再把同一条消息路由到三条分支之一。

### 1A) 声明式（主推）

```python
from masfactory import CustomNode, LogicSwitch, NodeTemplate, RootGraph


def score_content(d: dict) -> dict:
    text = str(d.get("content", ""))
    # 仅示例：按长度粗略打分（0~1）
    score = min(1.0, len(text) / 200.0)
    return {"content": text, "score": score}


def is_high(msg: dict, _attrs: dict) -> bool:
    return float(msg.get("score", 0.0)) >= 0.8


def is_mid(msg: dict, _attrs: dict) -> bool:
    s = float(msg.get("score", 0.0))
    return 0.5 <= s < 0.8


def is_low(msg: dict, _attrs: dict) -> bool:
    return float(msg.get("score", 0.0)) < 0.5


Router = NodeTemplate(LogicSwitch, routes={"high": is_high, "mid": is_mid, "low": is_low})

g = RootGraph(
    name="logic_switch_demo",
    nodes=[
        ("scorer", CustomNode, score_content),
        ("router", Router),
        ("high", CustomNode, lambda d: {"feedback": "内容很好：建议再补充 1-2 个更具体的例子。"}),
        ("mid", CustomNode, lambda d: {"feedback": "内容尚可：建议优化结构与论证链条。"}),
        ("low", CustomNode, lambda d: {"feedback": "内容偏弱：建议先明确主题，再列出要点逐条展开。"}),
    ],
    edges=[
        ("entry", "scorer", {"content": "待评估内容"}),
        ("scorer", "router", {"content": "原文", "score": "评分(0~1)"}),
        ("router", "high", {"content": "原文", "score": "评分"}),
        ("router", "mid", {"content": "原文", "score": "评分"}),
        ("router", "low", {"content": "原文", "score": "评分"}),
        ("high", "exit", {"feedback": "建议"}),
        ("mid", "exit", {"feedback": "建议"}),
        ("low", "exit", {"feedback": "建议"}),
    ],
)

g.build()
out, _attrs = g.invoke({"content": "今天我想谈谈环保的重要性，我们可以从节约用水开始……"})
print(out["feedback"])
```

### 1B) 命令式（备选）

```python
from masfactory import CustomNode, LogicSwitch, RootGraph


def score_content(d: dict) -> dict:
    text = str(d.get("content", ""))
    score = min(1.0, len(text) / 200.0)
    return {"content": text, "score": score}


def is_high(msg: dict, _attrs: dict) -> bool:
    return float(msg.get("score", 0.0)) >= 0.8


def is_mid(msg: dict, _attrs: dict) -> bool:
    s = float(msg.get("score", 0.0))
    return 0.5 <= s < 0.8


def is_low(msg: dict, _attrs: dict) -> bool:
    return float(msg.get("score", 0.0)) < 0.5


g = RootGraph(name="logic_switch_demo")

scorer = g.create_node(CustomNode, name="scorer", forward=score_content)
router = g.create_node(
    LogicSwitch,
    name="router",
    routes={"high": is_high, "mid": is_mid, "low": is_low},
)

high = g.create_node(CustomNode, name="high", forward=lambda d: {"feedback": "内容很好：建议再补充 1-2 个更具体的例子。"})
mid = g.create_node(CustomNode, name="mid", forward=lambda d: {"feedback": "内容尚可：建议优化结构与论证链条。"})
low = g.create_node(CustomNode, name="low", forward=lambda d: {"feedback": "内容偏弱：建议先明确主题，再列出要点逐条展开。"})

g.edge_from_entry(scorer, {"content": "待评估内容"})
g.create_edge(scorer, router, {"content": "原文", "score": "评分(0~1)"})

g.create_edge(router, high, {"content": "原文", "score": "评分"})
g.create_edge(router, mid, {"content": "原文", "score": "评分"})
g.create_edge(router, low, {"content": "原文", "score": "评分"})

g.edge_to_exit(high, {"feedback": "建议"})
g.edge_to_exit(mid, {"feedback": "建议"})
g.edge_to_exit(low, {"feedback": "建议"})

g.build()
out, _attrs = g.invoke({"content": "今天我想谈谈环保的重要性，我们可以从节约用水开始……"})
print(out["feedback"])
```

---

## 2) AgentSwitch：基于语义的路由（需要模型）

`AgentSwitch` 会让模型对每条分支条件做 YES/NO 判断，并把消息只发送到满足条件的分支。

### 2A) 声明式（主推）

```python
from masfactory import Agent, AgentSwitch, NodeTemplate, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

BaseAgent = NodeTemplate(Agent, model=model)

Router = NodeTemplate(
    AgentSwitch,
    model=model,
    routes={
        "tech_support": "用户问题涉及技术实现/报错/部署/接口调用等技术支持。",
        "product_consultant": "用户问题涉及产品功能/版本选择/价格方案/购买试用等咨询。",
        "customer_service": "用户问题涉及投诉/退款/纠纷/订单账号等客服事务。",
    },
)

g = RootGraph(
    name="agent_switch_demo",
    nodes=[
        ("router", Router),
        ("tech_support", BaseAgent(instructions="你是技术支持工程师。", prompt_template="{query}")),
        ("product_consultant", BaseAgent(instructions="你是产品顾问。", prompt_template="{query}")),
        ("customer_service", BaseAgent(instructions="你是客服经理。", prompt_template="{query}")),
    ],
    edges=[
        ("entry", "router", {"query": "用户咨询"}),
        ("router", "tech_support", {"query": "用户咨询"}),
        ("router", "product_consultant", {"query": "用户咨询"}),
        ("router", "customer_service", {"query": "用户咨询"}),
        ("tech_support", "exit", {"response": "回复"}),
        ("product_consultant", "exit", {"response": "回复"}),
        ("customer_service", "exit", {"response": "回复"}),
    ],
)

g.build()
out, _attrs = g.invoke({"query": "我的 API 调用总是返回 500，该怎么排查？"})
print(out["response"])
```

### 2B) 命令式（备选）

```python
from masfactory import Agent, AgentSwitch, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

g = RootGraph(name="agent_switch_demo")

router = g.create_node(
    AgentSwitch,
    name="router",
    model=model,
    routes={
        "tech_support": "用户问题涉及技术实现/报错/部署/接口调用等技术支持。",
        "product_consultant": "用户问题涉及产品功能/版本选择/价格方案/购买试用等咨询。",
        "customer_service": "用户问题涉及投诉/退款/纠纷/订单账号等客服事务。",
    },
)

tech_support = g.create_node(
    Agent,
    name="tech_support",
    model=model,
    instructions="你是技术支持工程师。",
    prompt_template="{query}",
)
product_consultant = g.create_node(
    Agent,
    name="product_consultant",
    model=model,
    instructions="你是产品顾问。",
    prompt_template="{query}",
)
customer_service = g.create_node(
    Agent,
    name="customer_service",
    model=model,
    instructions="你是客服经理。",
    prompt_template="{query}",
)

g.edge_from_entry(router, {"query": "用户咨询"})
g.create_edge(router, tech_support, {"query": "用户咨询"})
g.create_edge(router, product_consultant, {"query": "用户咨询"})
g.create_edge(router, customer_service, {"query": "用户咨询"})

g.edge_to_exit(tech_support, {"response": "回复"})
g.edge_to_exit(product_consultant, {"response": "回复"})
g.edge_to_exit(customer_service, {"response": "回复"})

g.build()
out, _attrs = g.invoke({"query": "我的 API 调用总是返回 500，该怎么排查？"})
print(out["response"])
```
