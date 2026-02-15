# Parallel Branching Example

This example demonstrates how to implement a parallel analysis workflow for plan feasibility in MASFactory, including: user requirement analysis, plan development, parallel evaluation of legal and economic feasibility, and final comprehensive report generation.

This workflow demonstrates a complete project evaluation process:

1. **Planner**: Develops detailed project plans based on user requirements
2. **Plan Distributor**: Distributes the developed plan to professional analysts
3. **Parallel Expert Analysis**:
   - **Legal Feasibility Expert**: Analyzes legal compliance and legal risks
   - **Economic Feasibility Expert**: Analyzes economic benefits and financial feasibility
4. **Final Report Expert**: Integrates all analysis results to generate a complete project evaluation report

## Message Passing View

- **Horizontal (Edge keys):** fan-out from `planner` to two branches, then fan-in into `final_reporter`
- **Vertical (attributes):** not used here; useful for global run status, retries, stage markers

## Diagram
![Diagram](/imgs/examples/parallel_branching.png)

## Example code (Declarative, recommended)

```python
from masfactory import Agent, NodeTemplate, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

BaseAgent = NodeTemplate(Agent, model=model)

graph = RootGraph(
    name="plan_feasibility_workflow",
    nodes=[
        ("planner", BaseAgent(instructions="You are a professional project planner. Produce a project plan from the user requirement.", prompt_template="User requirement: {requirement}")),
        ("legal_analyst", BaseAgent(instructions="You are a legal feasibility analyst. Identify compliance risks and legal blockers.", prompt_template="User requirement: {requirement}\nProject plan: {plan}")),
        ("economic_analyst", BaseAgent(instructions="You are an economic feasibility analyst. Evaluate cost, ROI, cashflow and financial risks.", prompt_template="User requirement: {requirement}\nProject plan: {plan}")),
        (
            "final_reporter",
            BaseAgent(
                instructions="You integrate the plan, legal analysis, and economic analysis into a comprehensive report.",
                prompt_template=(
                    "User requirement: {requirement}\n"
                    "Project plan: {plan}\n"
                    "Legal analysis: {legal_analysis}\n"
                    "Economic analysis: {economic_analysis}"
                ),
            ),
        ),
    ],
    edges=[
        ("entry", "planner", {"requirement": "User requirement description"}),
        # fan-out: planner output is sent to both branches
        ("planner", "legal_analyst", {"requirement": "User requirement", "plan": "Project plan"}),
        ("planner", "economic_analyst", {"requirement": "User requirement", "plan": "Project plan"}),
        # join: final_reporter has multiple incoming edges and waits for all open inputs
        ("planner", "final_reporter", {"requirement": "User requirement", "plan": "Project plan"}),
        ("legal_analyst", "final_reporter", {"legal_analysis": "Legal feasibility analysis"}),
        ("economic_analyst", "final_reporter", {"economic_analysis": "Economic feasibility analysis"}),
        ("final_reporter", "exit", {"report": "Final comprehensive report"}),
    ],
)

graph.build()

sample_requirement = """
I want to open a smart coffee shop in the city center, combining AI to provide personalized services.
The shop is about 200 square meters, with an investment budget of 1.5 million RMB. The plan is to use:
- an AI recommendation system,
- smart ordering,
- face-recognition membership,
to create a differentiated coffee experience.
The goal is to break even within one year and build brand influence.
"""

out, _attrs = graph.invoke({"requirement": sample_requirement})
print(out["report"])
```

## Example code (Imperative, alternative)

```python
from masfactory import Agent, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

graph = RootGraph(name="plan_feasibility_workflow")

planner = graph.create_node(
    Agent,
    name="planner",
    model=model,
    instructions="You are a professional project planner. Produce a project plan from the user requirement.",
    prompt_template="User requirement: {requirement}",
)
legal_analyst = graph.create_node(
    Agent,
    name="legal_analyst",
    model=model,
    instructions="You are a legal feasibility analyst. Identify compliance risks and legal blockers.",
    prompt_template="User requirement: {requirement}\nProject plan: {plan}",
)
economic_analyst = graph.create_node(
    Agent,
    name="economic_analyst",
    model=model,
    instructions="You are an economic feasibility analyst. Evaluate cost, ROI, cashflow and financial risks.",
    prompt_template="User requirement: {requirement}\nProject plan: {plan}",
)
final_reporter = graph.create_node(
    Agent,
    name="final_reporter",
    model=model,
    instructions="You integrate the plan, legal analysis, and economic analysis into a comprehensive report.",
    prompt_template=(
        "User requirement: {requirement}\n"
        "Project plan: {plan}\n"
        "Legal analysis: {legal_analysis}\n"
        "Economic analysis: {economic_analysis}"
    ),
)

graph.edge_from_entry(planner, {"requirement": "User requirement description"})

graph.create_edge(planner, legal_analyst, {"requirement": "User requirement", "plan": "Project plan"})
graph.create_edge(planner, economic_analyst, {"requirement": "User requirement", "plan": "Project plan"})

graph.create_edge(planner, final_reporter, {"requirement": "User requirement", "plan": "Project plan"})
graph.create_edge(legal_analyst, final_reporter, {"legal_analysis": "Legal feasibility analysis"})
graph.create_edge(economic_analyst, final_reporter, {"economic_analysis": "Economic feasibility analysis"})

graph.edge_to_exit(final_reporter, {"report": "Final comprehensive report"})

graph.build()
sample_requirement = """
I want to open a smart coffee shop in the city center, combining AI to provide personalized services.
The shop is about 200 square meters, with an investment budget of 1.5 million RMB. The plan is to use:
- an AI recommendation system,
- smart ordering,
- face-recognition membership,
to create a differentiated coffee experience.
The goal is to break even within one year and build brand influence.
"""

out, _attrs = graph.invoke({"requirement": sample_requirement})
print(out["report"])
```
