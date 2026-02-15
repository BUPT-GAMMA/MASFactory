# Agents (SingleAgent / Agent / DynamicAgent)

MASFactory commonly uses three Agent shapes:

- `SingleAgent`: standalone, direct `invoke(dict)` (no graph)
- `Agent`: a graph node whose input/output fields are defined by edges (most common)
- `DynamicAgent`: a graph node that can **override instructions per run** via an input field

## Message Passing View

- **Horizontal (Edge keys):** Agents consume fields from edges and output structured fields.
- **Vertical (attributes):** Agents do not inherit/write attributes by default; enable with `pull_keys/push_keys` when needed.

## Diagram
![Diagram](/imgs/examples/agent.png)

---

## 1) SingleAgent (standalone)

```python
from masfactory import OpenAIModel, SingleAgent

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

agent = SingleAgent(
    name="demo_single",
    model=model,
    instructions="Reply in JSON with field {answer}.",
    prompt_template="Question: {query}",
)

out = agent.invoke({"query": "Explain what a DAG is in one sentence."})
print(out)  # dict parsed by the output formatter
```

::: warning
`SingleAgent` cannot be embedded into `Graph/RootGraph`. Use `Agent` inside graphs.
:::

---

## 2) Agent inside a graph (recommended)

### 2A) Declarative (recommended)

```python
from masfactory import Agent, NodeTemplate, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

BaseAgent = NodeTemplate(Agent, model=model)

g = RootGraph(
    name="agent_in_graph",
    nodes=[
        ("writer", BaseAgent(instructions="You are a writer.", prompt_template="Topic: {topic}")),
        ("critic", BaseAgent(instructions="You are a reviewer.", prompt_template="Draft: {draft}")),
    ],
    edges=[
        ("entry", "writer", {"topic": "topic"}),
        ("writer", "critic", {"draft": "draft"}),
        ("critic", "exit", {"review": "review feedback"}),
    ],
)

g.build()
out, _attrs = g.invoke({"topic": "Explain MASFactory's value in 3 bullet points."})
print(out["review"])
```

### 2B) Imperative (alternative)

```python
from masfactory import Agent, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

g = RootGraph(name="agent_in_graph")

writer = g.create_node(
    Agent,
    name="writer",
    model=model,
    instructions="You are a writer.",
    prompt_template="Topic: {topic}",
)
critic = g.create_node(
    Agent,
    name="critic",
    model=model,
    instructions="You are a reviewer.",
    prompt_template="Draft: {draft}",
)

g.edge_from_entry(writer, {"topic": "topic"})
g.create_edge(writer, critic, {"draft": "draft"})
g.edge_to_exit(critic, {"review": "review feedback"})

g.build()
out, _attrs = g.invoke({"topic": "Explain MASFactory's value in 3 bullet points."})
print(out["review"])
```

::: tip
You can inspect `agent.last_prompt` to debug missing fields / formatting issues.
:::

---

## 3) DynamicAgent: override instructions at runtime

Scenario: upstream decides a role, then passes `instructions` to one shared `DynamicAgent`.

### 3A) Declarative (recommended)

```python
from masfactory import CustomNode, DynamicAgent, NodeTemplate, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)


def choose_role(d: dict) -> dict:
    q = str(d.get("query", ""))
    if "refund" in q.lower() or "complaint" in q.lower():
        ins = "You are a customer service manager. Be calm and professional."
    elif "price" in q.lower() or "plan" in q.lower():
        ins = "You are a product consultant. Answer features/pricing."
    else:
        ins = "You are a tech support engineer. Help debug errors."
    return {"instructions": ins, "query": q}


Dynamic = NodeTemplate(
    DynamicAgent,
    model=model,
    default_instructions="You are a helpful assistant.",
    instruction_key="instructions",
    prompt_template="{query}",
)

g = RootGraph(
    name="dynamic_agent_demo",
    nodes=[
        ("role_selector", CustomNode, choose_role),
        ("service", Dynamic),
    ],
    edges=[
        ("entry", "role_selector", {"query": "user query"}),
        ("role_selector", "service", {"instructions": "role instructions", "query": "user query"}),
        ("service", "exit", {"response": "response"}),
    ],
)

g.build()
out, _attrs = g.invoke({"query": "I want a refund. The service is not acceptable."})
print(out["response"])
```

### 3B) Imperative (alternative)

```python
from masfactory import CustomNode, DynamicAgent, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)


def choose_role(d: dict) -> dict:
    q = str(d.get("query", ""))
    if "refund" in q.lower() or "complaint" in q.lower():
        ins = "You are a customer service manager. Be calm and professional."
    elif "price" in q.lower() or "plan" in q.lower():
        ins = "You are a product consultant. Answer features/pricing."
    else:
        ins = "You are a tech support engineer. Help debug errors."
    return {"instructions": ins, "query": q}


g = RootGraph(name="dynamic_agent_demo")

role_selector = g.create_node(CustomNode, name="role_selector", forward=choose_role)
service = g.create_node(
    DynamicAgent,
    name="service",
    model=model,
    default_instructions="You are a helpful assistant.",
    instruction_key="instructions",
    prompt_template="{query}",
)

g.edge_from_entry(role_selector, {"query": "user query"})
g.create_edge(role_selector, service, {"instructions": "role instructions", "query": "user query"})
g.edge_to_exit(service, {"response": "response"})

g.build()
out, _attrs = g.invoke({"query": "I want a refund. The service is not acceptable."})
print(out["response"])
```
