# Sequential Workflow

This example demonstrates how to build a simple sequential execution workflow where multiple nodes execute in order according to dependency relationships.

## Message Passing View

- **Horizontal (Edge keys):** `user_question -> requirements_report -> codes`
- **Vertical (attributes):** not used in this example; add when shared workflow state is needed (`/examples/attributes`)

## Diagram
![Diagram](/imgs/examples/sequential_workflow.png)

## Example code (Declarative, recommended)

```python
from masfactory import Agent, OpenAIModel, RootGraph, NodeTemplate

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

BaseAgent = NodeTemplate(Agent, model=model)

graph = RootGraph(
    name="demo",
    nodes=[
        ("analyser", BaseAgent(instructions="You are a product manager. Perform requirement analysis.", prompt_template="User request: {user_question}")),
        ("coder", BaseAgent(instructions="You are a senior programmer. Write code based on the requirements report.", prompt_template="Requirements report: {requirements_report}")),
    ],
    edges=[
        ("entry", "analyser", {"user_question": "User request"}),
        ("analyser", "coder", {"requirements_report": "Requirements analysis report"}),
        ("coder", "exit", {"codes": "Generated code"}),
    ],
)

graph.build()
out, _attrs = graph.invoke({"user_question": "Write a Python function that adds two numbers."})
print(out["codes"])
```

::: tip Tip
`RootGraph.invoke(...)` returns `(output_dict, attributes_dict)`.
:::

## Example code (Imperative, alternative)

```python
from masfactory import Agent, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

graph = RootGraph(name="demo")

analyser = graph.create_node(
    Agent,
    name="analyser",
    model=model,
    instructions="You are a product manager. Analyze the user request and output a requirements report.",
    prompt_template="User request: {user_question}",
)

coder = graph.create_node(
    Agent,
    name="coder",
    model=model,
    instructions="You are a senior programmer. Write Python code based on the requirements report.",
    prompt_template="Requirements report: {requirements_report}",
)

graph.edge_from_entry(analyser, {"user_question": "User request"})
graph.create_edge(analyser, coder, {"requirements_report": "Requirements analysis report"})
graph.edge_to_exit(coder, {"codes": "Generated code"})

graph.build()
out, _attrs = graph.invoke({"user_question": "Write a Python function that adds two numbers."})
print(out["codes"])
```
