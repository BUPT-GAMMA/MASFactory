# Declarative vs. Imperative: Two Development Paradigms

MASFactory supports two paradigms for building workflows:

- **Declarative**: declare the topology **in one place** when instantiating `RootGraph/Graph/Loop`. During `build()`, MASFactory **assembles** nodes/edges and performs consistency checks.
- **Imperative**: create a `Graph/RootGraph/Loop` first, then **incrementally** add nodes and edges by calling `create_node()` / `create_edge()`. This reads like issuing construction commands to a graph, hence “imperative”.

::: tip Choosing between them
- If your workflow structure is **static**, declarative is usually more direct and maintainable.
- If parts of the topology are determined at runtime (e.g., by hyperparameters), imperative gives you more flexibility.
:::

---

## 1) The same workflow in two styles

Back to the example in [First Code](/start/the_first_code), we can implement it in two equivalent ways.

These two snippets behave the same at runtime; the difference is how you organize the **graph-assembly** stage.

`entry -> analyze -> answer -> exit`

### Declarative

```python
from masfactory import RootGraph, Agent, OpenAIModel, NodeTemplate

# 1) Model configuration (in real projects, read from env vars / config files)
model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_API_URL",
    model_name="gpt-4o-mini",
)

# 2) A reusable node template (create multiple similar Agent nodes)
BaseAgent = NodeTemplate(Agent, model=model)

# 3) Declarative assembly: declare nodes/edges up front; build() assembles and validates
g = RootGraph(
    name="qa_two_stage_decl",
    nodes=[
        ("analyze", BaseAgent(instructions="You analyze the problem.", prompt_template="Question: {query}")),
        (
            "answer",
            NodeTemplate(
                Agent,
                model=model,
                instructions="You provide the final answer based on the analysis.",
                prompt_template="Question: {query}\nAnalysis: {analysis}",
            ),
        ),
    ],
    edges=[
        ("entry", "analyze", {"query": "User question"}),
        ("analyze", "answer", {"query": "Original question", "analysis": "Analysis result"}),
        ("answer", "exit", {"answer": "Final answer"}),
    ],
)

g.build()
out, _attrs = g.invoke({"query": "I want to learn Python. Where should I start?"})
print(out["answer"])
```

### Imperative

```python
from masfactory import RootGraph, Agent, OpenAIModel, NodeTemplate

# 1) Model configuration
model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",  # Official OpenAI: "https://api.openai.com/v1"
    model_name="gpt-4o-mini",
)

# 2) Imperative assembly: create the graph first, then add nodes/edges step by step
g = RootGraph(name="qa_two_stage_imp")

BaseAgent = NodeTemplate(Agent, model=model)  # NodeTemplate is also useful in imperative style

# Create nodes (create_node)
analyze = g.create_node(
    BaseAgent,
    name="analyze",
    instructions="You analyze the problem.",
    prompt_template="Question: {query}",
)
answer = g.create_node(
    Agent,  # Without NodeTemplate
    name="answer",
    instructions="You provide the final answer based on the analysis.",
    model=model,
    prompt_template="Question: {query}\nAnalysis: {analysis}",
)

# Create edges (edge_from_entry / create_edge / edge_to_exit)
g.edge_from_entry(analyze, {"query": "User question"})
g.create_edge(analyze, answer, {"query": "Original question", "analysis": "Analysis result"})
g.edge_to_exit(answer, {"answer": "Final answer"})

g.build()
out, _attrs = g.invoke({"query": "I want to learn Python. Where should I start?"})
print(out["answer"])
```

---

## 2) Advanced: how to choose and write robustly

This page focuses on an entry-level side-by-side example. For a more systematic discussion of trade-offs, best practices and common pitfalls, see:

- [Declarative vs. Imperative (Advanced)](/guide/declarative_vs_imperative_advanced)
