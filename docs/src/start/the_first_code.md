# First Code (0 → 1)

Goal: write a **runnable** MASFactory workflow in minutes and understand the essential APIs:
`RootGraph / Node / Edge / build / invoke`.

---

## 0) Two concepts to understand first

1) **MASFactory uses Python `dict` as the message carrier**. Inputs, node outputs, and edge payloads are all structured as `dict`. The smallest unit of message exchange is a single field in that dict.

- **Horizontal message passing**: nodes exchange payloads through `Edge` inside the same graph. `Edge.keys` defines the field contract and routing rule (“which fields flow across this hop”).
- **Vertical message passing**: a node exchanges state with its containing graph through `attributes` (node attributes). `pull_keys / push_keys` decide which fields are read from / written back to `attributes`.
- For details, see: [Message Passing](/guide/message_passing).

2) `RootGraph.invoke(...)` **returns a tuple**: `(output_dict, attributes_dict)`. The first item is the final output of horizontal passing; the second item is a snapshot of the graph attributes (vertical state).

### Diagram: Horizontal (Edge) + Vertical (attributes)
<ThemedDiagram light="/imgs/message/overview-en-light.svg" dark="/imgs/message/overview-en-dark.svg" alt="Message overview: horizontal (Edge) + vertical (attributes)" />

---

## 1) Your first Agent workflow

We build a simple QA workflow with two agents: one for analysis and one for answering.

### Diagram: analyze → answer
<ThemedDiagram
  light="/imgs/tutorial/first-agent-workflow-en-light.svg"
  dark="/imgs/tutorial/first-agent-workflow-en-dark.svg"
  alt="First Agent workflow: ENTRY → analyze → answer → EXIT"
/>

```python
from masfactory import RootGraph, Agent, OpenAIModel, NodeTemplate, HistoryMemory

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

history = HistoryMemory(top_k=12)
BaseAgent = NodeTemplate(Agent, model=model, memories=[history])

g = RootGraph(
    name="qa_two_stage",
    nodes=[
        ("analyze", BaseAgent(instructions="You are a problem analysis expert.", prompt_template="User question: {query}")),
        ("answer", BaseAgent(instructions="You are a solution expert. Provide the final answer based on the analysis.", prompt_template="Question: {query}\nAnalysis: {analysis}")),
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

::: tip Read model config from environment variables
MASFactory does not auto-load environment variables. You can wire them in yourself:

```python
import os
from masfactory import OpenAIModel

model = OpenAIModel(
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL") or None,
    model_name=os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
)
```

:::

::: tip Why doesn’t an Agent read `attributes` by default?
`Agent.pull_keys / Agent.push_keys` defaults to `{}`. With this setting, an agent does not read from or write back to graph attributes.  
If you want an agent to read from attributes, explicitly set `pull_keys` to the required fields. If you set `pull_keys=None`, it will inherit all attributes.
:::

---

## 3) What to read next?

- For a systematic understanding of declarative orchestration: read the **Development Guide** and **Examples**.
- For runnable side-by-side comparisons: run `examples/run_all.py` in this repo (includes Imperative vs Declarative comparisons).
