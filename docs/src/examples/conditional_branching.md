# Conditional Branching (LogicSwitch / AgentSwitch)

MASFactory provides two common routing components:

- `LogicSwitch`: route by **Python predicates** (offline runnable)
- `AgentSwitch`: route by **LLM semantic evaluation** (requires a model)

## Message Passing View

- **Horizontal (Edge keys):** fields flow into `router`, then the router forwards to selected branches
- **Vertical (attributes):** route predicates can read attributes; this page is horizontal-first

## Diagram

![Diagram](/imgs/examples/conditional_branching_logic.png)

## 1) LogicSwitch: rule-based routing (offline)

Example: score content, then route into one of three branches.

### 1A) Declarative (recommended)

```python
from masfactory import CustomNode, LogicSwitch, NodeTemplate, RootGraph


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


Router = NodeTemplate(LogicSwitch, routes={"high": is_high, "mid": is_mid, "low": is_low})

g = RootGraph(
    name="logic_switch_demo",
    nodes=[
        ("scorer", CustomNode, score_content),
        ("router", Router),
        ("high", CustomNode, lambda d: {"feedback": "High quality. Add 1-2 more concrete examples."}),
        ("mid", CustomNode, lambda d: {"feedback": "Decent. Improve structure and reasoning."}),
        ("low", CustomNode, lambda d: {"feedback": "Weak. Clarify the topic and expand key points."}),
    ],
    edges=[
        ("entry", "scorer", {"content": "content"}),
        ("scorer", "router", {"content": "content", "score": "score (0..1)"}),
        ("router", "high", {"content": "content", "score": "score"}),
        ("router", "mid", {"content": "content", "score": "score"}),
        ("router", "low", {"content": "content", "score": "score"}),
        ("high", "exit", {"feedback": "feedback"}),
        ("mid", "exit", {"feedback": "feedback"}),
        ("low", "exit", {"feedback": "feedback"}),
    ],
)

g.build()
out, _attrs = g.invoke({"content": "Environmental protection matters. Save water and reduce waste..."})
print(out["feedback"])
```

### 1B) Imperative (alternative)

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
router = g.create_node(LogicSwitch, name="router", routes={"high": is_high, "mid": is_mid, "low": is_low})
high = g.create_node(CustomNode, name="high", forward=lambda d: {"feedback": "High quality. Add 1-2 more concrete examples."})
mid = g.create_node(CustomNode, name="mid", forward=lambda d: {"feedback": "Decent. Improve structure and reasoning."})
low = g.create_node(CustomNode, name="low", forward=lambda d: {"feedback": "Weak. Clarify the topic and expand key points."})

g.edge_from_entry(scorer, {"content": "content"})
g.create_edge(scorer, router, {"content": "content", "score": "score (0..1)"})
g.create_edge(router, high, {"content": "content", "score": "score"})
g.create_edge(router, mid, {"content": "content", "score": "score"})
g.create_edge(router, low, {"content": "content", "score": "score"})
g.edge_to_exit(high, {"feedback": "feedback"})
g.edge_to_exit(mid, {"feedback": "feedback"})
g.edge_to_exit(low, {"feedback": "feedback"})

g.build()
out, _attrs = g.invoke({"content": "Environmental protection matters. Save water and reduce waste..."})
print(out["feedback"])
```

---

## 2) AgentSwitch: semantic routing (requires model)

`AgentSwitch` asks the LLM a YES/NO question per branch condition, then routes to the matching branches.

### 2A) Declarative (recommended)

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
        "tech_support": "Technical support: errors, debugging, deployment, API calls.",
        "product_consultant": "Product consulting: features, plans, pricing, trials.",
        "customer_service": "Customer service: complaint, refund, disputes, orders/accounts.",
    },
)

g = RootGraph(
    name="agent_switch_demo",
    nodes=[
        ("router", Router),
        ("tech_support", BaseAgent(instructions="You are a tech support engineer.", prompt_template="{query}")),
        ("product_consultant", BaseAgent(instructions="You are a product consultant.", prompt_template="{query}")),
        ("customer_service", BaseAgent(instructions="You are a customer service manager.", prompt_template="{query}")),
    ],
    edges=[
        ("entry", "router", {"query": "user query"}),
        ("router", "tech_support", {"query": "user query"}),
        ("router", "product_consultant", {"query": "user query"}),
        ("router", "customer_service", {"query": "user query"}),
        ("tech_support", "exit", {"response": "response"}),
        ("product_consultant", "exit", {"response": "response"}),
        ("customer_service", "exit", {"response": "response"}),
    ],
)

g.build()
out, _attrs = g.invoke({"query": "My API calls return 500. How do I debug this?"})
print(out["response"])
```

### 2B) Imperative (alternative)

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
        "tech_support": "Technical support: errors, debugging, deployment, API calls.",
        "product_consultant": "Product consulting: features, plans, pricing, trials.",
        "customer_service": "Customer service: complaint, refund, disputes, orders/accounts.",
    },
)

tech_support = g.create_node(Agent, name="tech_support", model=model, instructions="You are a tech support engineer.", prompt_template="{query}")
product_consultant = g.create_node(Agent, name="product_consultant", model=model, instructions="You are a product consultant.", prompt_template="{query}")
customer_service = g.create_node(Agent, name="customer_service", model=model, instructions="You are a customer service manager.", prompt_template="{query}")

g.edge_from_entry(router, {"query": "user query"})
g.create_edge(router, tech_support, {"query": "user query"})
g.create_edge(router, product_consultant, {"query": "user query"})
g.create_edge(router, customer_service, {"query": "user query"})
g.edge_to_exit(tech_support, {"response": "response"})
g.edge_to_exit(product_consultant, {"response": "response"})
g.edge_to_exit(customer_service, {"response": "response"})

g.build()
out, _attrs = g.invoke({"query": "My API calls return 500. How do I debug this?"})
print(out["response"])
```
