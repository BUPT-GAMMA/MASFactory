<div align="center">
  <img
    src="docs/src/public/svg/logo.svg#gh-light-mode-only"
    alt="MASFactory"
    width="620"
  />
  <img
    src="docs/src/public/svg/logo-dark.svg#gh-dark-mode-only"
    alt="MASFactory"
    width="620"
  />
</div>
<p align="center">
    【English   | <a href="README.zh.md">Chinese</a>】
</p>

## 📖 Overview

**MASFactory** is a composable framework for orchestrating Multi-Agent Systems with  **Vibe Graphing**:

start from intent, sketch a graph, converge the structure via visual preview/editing, compile it into an executable workflow,
and trace runtime states/messages/shared-attributes end-to-end with **MASFactory Visualizer**.

Documentation: https://bupt-gamma.github.io/MASFactory/

Key capabilities:

- **Vibe Graphing (intent → graph):** generate a draft structure from intent, then iterate toward an executable workflow.
- **Graph composability:** scale from simple pipelines to complex workflows with subgraphs, loops, switches, and composite components.
- **Visualization & observability:** preview topology, trace runtime events, and handle human-in-the-loop requests in VS Code.
- **Context protocol (ContextBlock):** structure and inject Memory / RAG / MCP context in a controllable way.

## ⚡ Quick Start

### 1) Install MASFactory (PyPI)

Requirements: Python `>= 3.10`

```bash
pip install -U masfactory
```

Verify installation:

```bash
python -c "import masfactory; print('masfactory version:', masfactory.__version__)"
python -c "from masfactory import RootGraph, Graph, Loop, Agent, CustomNode; print('import ok')"
```

### 2) Install MASFactory Visualizer (VS Code)

MASFactory Visualizer is a VS Code extension for graph preview, runtime tracing, and human-in-the-loop interactions.

Install from VS Code Marketplace:

1. Open VS Code → Extensions
2. Search: `MASFactory Visualizer`
3. Install and reload

Open it:
- Activity Bar → **MASFactory Visualizer** → **Graph Preview**, or
- Command Palette:
  - `MASFactory Visualizer: Start Graph Preview`
  - `MASFactory Visualizer: Open Graph in Editor Tab`

## 🧩 Simple Example (from “First Code”)

This is a minimal two-agent workflow: **ENTRY → analyze → answer → EXIT**.

```python
import os
from masfactory import RootGraph, Agent, OpenAIModel, NodeTemplate

model = OpenAIModel(
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL") or None,
    model_name=os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
)

BaseAgent = NodeTemplate(Agent, model=model)

g = RootGraph(
    name="qa_two_stage",
    nodes=[
        ("analyze", BaseAgent(instructions="You analyze the problem.", prompt_template="Question: {query}")),
        ("answer", BaseAgent(instructions="You provide the final answer.", prompt_template="Question: {query}\nAnalysis: {analysis}")),
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

## ▶️ Run multi-agent reproductions (applications/)

Most workflows require `OPENAI_API_KEY`. Some scripts also read `OPENAI_BASE_URL` / `BASE_URL` and `OPENAI_MODEL_NAME`.

```bash
# ChatDev
python applications/chatdev/workflow/main.py --task "Develop a basic Gomoku game." --name "Gomoku"

# ChatDev Lite (simplified)
python applications/chatdev_lite/workflow/main.py --task "Develop a basic Gomoku game." --name "Gomoku"

# ChatDev Lite (VibeGraphing version)
python applications/chatdev_lite_vibegraph/main.py --task "Write a Ping-Pong (Pong) game." --name "PingPong"

# VibeGraph demo (intent → graph_design.json → compile → run)
python applications/vibegraph_demo/main.py

# AgentVerse · PythonCalculator task
python applications/agentverse/tasksolving/pythoncalculator/run.py --task "write a simple calculator GUI using Python3."

# CAMEL role-playing demo
python applications/camel/main.py "Create a sample adder by using python"
```

## 📚 Learn MASFactory (docs outline)
Online documentation: https://bupt-gamma.github.io/MASFactory/
- Quick Start: Introduction → Installation → Visualizer → First Code
- Progressive Tutorials: ChatDev Lite (Declarative / Imperative / VibeGraph)
- Development Guide: Concepts → Message Passing → NodeTemplate → Agent Runtime → Context Adapters → Visualizer → Model Adapters

## 🗂️ Project structure

```
.
├── masfactory/               # MASFactory Framework
│   ├── core/                 # Foundation: Node / Edge / Gate / Message
│   ├── components/           # Components (Agents / Graphs / Controls / CustomNode)
│   │   ├── agents/           # Agent, DynamicAgent, SingleAgent
│   │   ├── graphs/           # BaseGraph, Graph, RootGraph, Loop
│   │   └── controls/         # LogicSwitch, AgentSwitch
│   ├── adapters/             # Adapters (Model / Tool / Memory / Retrieval / MCP)
│   │   └── context/          # Context pipeline (ContextBlock / policy / renderer / composer)
│   ├── integrations/         # 3rd-party integrations (MemoryOS / UltraRAG, etc.)
│   ├── utils/                # Utilities (config, hook, Embedding, etc.)
│   ├── resources/            # Resources and static files
│   └── visualizer/           # MASFactory Visualizer runtime integration
├── masfactory-visualizer/    # VSCode extension: MASFactory Visualizer
├── applications/             # Examples and reproductions based on MASFactory
│   ├── chatdev_lite/
│   ├── chatdev/
│   ├── agentverse/
│   ├── camel/
│   └── number_off_demo.py
├── docs/                     # VitePress docs
│   ├── .vitepress/
│   └── src/
│       ├── zh/
│       └── en/
├── examples/                 # Graph patterns (imperative vs declarative)
├── README.md                 # English (default)
├── README.zh.md              # Chinese
├── pyproject.toml
├── requirements.txt
└── uv.lock
```
