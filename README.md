<div align="center">
  <img
    src="docs/src/public/svg/logo-centered.svg#gh-light-mode-only"
    alt="MASFactory"
    width="620"
  />
  <img
    src="docs/src/public/svg/logo-dark-centered.svg#gh-dark-mode-only"
    alt="MASFactory"
    width="620"
  />
</div>
<p align="center">
  <a href="README.zh.md">
    <img alt="Chinese README" src="https://img.shields.io/badge/README-%E4%B8%AD%E6%96%87-5c7cfa" />
  </a>
  <a href="http://arxiv.org/abs/2603.06007">
    <img alt="Paper" src="https://img.shields.io/badge/Paper%20%7C%20-2603.06007-b31b1b?logo=arxiv&logoColor=white" />
  </a>
  <a href="https://www.youtube.com/watch?v=QFlQuX_cddk">
    <img alt="Video Vibe Graphing" src="https://img.shields.io/badge/Video%20%7C%20-Vibe%20Graphing-ff0000?logo=youtube&logoColor=white" />
  </a>
  <a href="https://www.youtube.com/watch?v=ANynzVfY32k">
    <img alt="Video Demonstration" src="https://img.shields.io/badge/Video%20%7C%20-Demo-d35400?logo=youtube&logoColor=white" />
  </a>
  <a href="LICENSE">
    <img alt="License" src="https://img.shields.io/badge/License-Apache%202.0-5b8c5a" />
  </a>
  <br />
  <a href="https://discord.gg/RWRYhWq7">
    <img alt="Discord" src="https://img.shields.io/badge/Contact-Discord-5865F2?logo=discord&logoColor=white" />
  </a>
  <a href="https://qm.qq.com/cgi-bin/qm/qr?k=jTn5-wNlUg2SZ0OfyMlA4h9eqBx4OX6x&amp;jump_from=webapi&amp;authKey=NDNs1xg1usRYTIuO7XsgQjJVYqwntJL6NX1pOmR9J15tAPoJ8B3NSAVTD1tnR2+m">
    <img alt="QQ" src="https://img.shields.io/badge/Contact-QQ-12B7F5?logo=qq&logoColor=white" />
  </a>
</p>

**MASFactory** is a graph-centric framework for orchestrating Multi-Agent Systems with **Vibe Graphing**:

Start from intent, generate a graph design, preview and refine it in a visual environment, compile it into an executable workflow, and trace node states, messages, and shared state at runtime.

- Paper: http://arxiv.org/abs/2603.06007
- Documentation: https://docs.masfactory.dev/
- Project Website: https://masfactory.dev
- Demonstration Video: https://www.youtube.com/watch?v=ANynzVfY32k
- Vibe Graphing explainer (Discover AI): https://www.youtube.com/watch?v=QFlQuX_cddk

## ✨ Key Features

- 🪄 **Vibe Graphing (intent → graph)**  
  Turn natural-language intent into a structural design, then iteratively converge to an executable, reusable workflow.
- 🧱 **Graph-style composition**  
  Describe workflow and field contracts explicitly with `Node` / `Edge`; supports subgraphs, loops, branches, and composite components.
- 👁️ **Visualization and observability**  
  **MASFactory Visualizer** provides topology preview, runtime tracing, and human-in-the-loop interaction.
- 🧠 **Context protocol (`ContextBlock`)**  
  Organize Memory / RAG / MCP context sources in a structured way, with automatic injection and on-demand retrieval.

## 🧭 Why Choose MASFactory

As multi-agent systems grow more capable, orchestration is still largely stuck in the age of manual assembly: either teams hand-write workflow code, or they drag and configure nodes one by one on a canvas. With Vibe Graphing, MASFactory aims to free people from tedious orchestration work: express the intent in natural language, let AI draft the collaboration structure, keep refining it with human corrections and confirmations, and finally compile the result into an executable graph workflow.

<p align="center">
  <img
    src="docs/src/public/imgs/readme/vibegraphing_diagram_en.png"
    alt="Vibe Graphing pipeline from intent to executable workflow"
    width="780"
  />
</p>

This shifts human effort away from low-level wiring and repetitive configuration, and back toward designing the multi-agent system itself.

Viewed more directly, today's multi-agent development frameworks roughly fall into the following categories:

| Platform | Products | Focus | Strength & Limits |
| --- | --- | --- | --- |
| **Code frameworks** | `MASFactory`, ChatDev2(DevAll), LangGraph, AutoGen | Build complex multi-agent systems | Offer extremely high flexibility and extensibility, but have a higher entry barrier, require learning a DSL, and usually involve substantial development cost |
| **Low-code workflow platforms** | `MASFactory`, ChatDev2(DevAll), Coze, Dify | Lower the barrier to building multi-agent systems with low-code workflows | Lower the development barrier, but still rely heavily on manual human orchestration |
| **Vibe Graphing orchestration frameworks** | `MASFactory` | Rapidly design and iterate multi-agent systems with lower human cost | Humans do not need to spend much effort on coding or dragging nodes, only on clearly describing needs and refining the design through dialogue |

## 🏗️ System Architecture

MASFactory adopts the widely used graph-centric approach to multi-agent orchestration and abstracts the system into four layers:

<p align="center">
  <img
    src="docs/src/public/imgs/readme/framework.png"
    alt="MASFactory framework layers"
    width="860"
  />
</p>

- **Graph skeleton layer:** `Node` and `Edge` are the lowest-level abstractions, using graph structure to represent collaboration relationships, dependencies, and message flow among agents.
- **Component layer:** this layer further packages `Node` and `Edge` into reusable collaboration units, so developers do not need to assemble workflows from scratch every time and can instead build multi-agent systems like reusable blocks:

> - `Agent` is the most basic execution unit: an agent node with roles, instructions, tools, Memory, RAG, and related capabilities, responsible for concrete analysis, generation, and tool-use tasks.
>
> - `Graph` packages multiple nodes as a nestable subgraph, allowing complex workflows to be designed hierarchically and reused locally. A single phase can itself become a node inside a larger graph.
>
> - `Loop` handles iterative tasks such as repeated discussion, continuous revision, or testing until success. It turns "repeat execution until a condition is met" into a standard component.
>
> - `Switch` supports branching and dynamic routing. It can switch execution paths based on explicit conditions or use model capabilities to decide where messages should go, enabling more flexible collaboration topologies.
>
> - `Human` brings human-in-the-loop steps such as confirmation, conversational input, file review, and editing into the graph, so the system is not limited to fully automated execution and can involve people at key stages.
>
> - `ComposedGraph` and `NodeTemplate` provide two additional reuse mechanisms on top of the components above. The former focuses on "declare a structure first, then instantiate and assemble it," while the latter packages common collaboration structures into reusable components. MASFactory includes built-in graph patterns such as `InstructorAssistantGraph` and `BrainstormingGraph` for out-of-the-box use.

  **Protocol layer:** through `Message Adapter` and `Context Adapter`, MASFactory unifies communication protocols together with Memory, RAG, MCP, and related context capabilities, making it easier to integrate external frameworks into the system.

- **Interaction layer:** MASFactory supports three development paradigms:

 > - Natural-language workflow construction based on `Vibe Graphing`, reducing the human cost of system development.
 > - Two code-centric styles, `Declarative` and `Imperative`, for developers who want more flexible control over workflow authoring.
 > - Manual workflow design through `MASFactory Visualizer`, preserving familiar low-code drag-and-drop habits.

MASFactory's advantage is not that it offers yet another way to build workflows, but that it unifies code authoring, visual editing, and natural-language-driven orchestration inside the same system. Developers can write workflows by hand, assemble them visually, or let AI draft the structure first and then compile it into an executable multi-agent workflow. These three modes are not isolated from one another; they can coexist inside the same project.

## 🎬 Flexible Combination of Three Development Modes with Unified Runtime Tracing

Whether you start from code, drag-and-drop editing, or Vibe Graphing, the resulting graph structure can enter the same Visualizer for preview, tracing, and human intervention.

### Coding with Graph Preview

<p align="center">
  <img src="docs/src/public/imgs/readme/coding.gif" alt="Code preview in MASFactory Visualizer" width="860" />
</p>

### Drag-and-Drop Design

<p align="center">
  <img src="docs/src/public/imgs/readme/drag.gif" alt="Drag and drop workflow design" width="860" />
</p>

### Vibe Graphing Interaction

<p align="center">
  <img src="docs/src/public/imgs/readme/vibe_2.gif" alt="Vibe Graphing interaction" width="860" />
</p>

### Runtime Monitoring

<p align="center">
  <img src="docs/src/public/imgs/readme/monitor.gif" alt="Runtime monitoring and tracing" width="860" />
</p>

## ⚡ Quick Start

### 1) Install MASFactory (PyPI)

Requirements: Python `>= 3.10`

```bash
pip install -U masfactory
```

Verify installation:

```bash
python -c "from importlib.metadata import version; print('masfactory version:', version('masfactory'))"
python -c "from masfactory import RootGraph, Graph, Loop, Agent, CustomNode; print('import ok')"
```

### 2) Install MASFactory Visualizer (VS Code Extension)

MASFactory Visualizer is used for graph preview, runtime tracing, and human-in-the-loop interaction.

Install from the VS Code Marketplace:

1. Open VS Code → Extensions
2. Search for `MASFactory Visualizer`
3. Install and reload

Open it via:
- Activity Bar → **MASFactory Visualizer** → **Graph Preview**, or
- Command Palette:
  - `MASFactory Visualizer: Start Graph Preview`
  - `MASFactory Visualizer: Open Graph in Editor Tab`

## 🧩 Simple Example (from "First Code")

A minimal two-stage agent workflow: **ENTRY → analyze → answer → EXIT**.

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

## 🛠️ Reusable Skill Example

Skills are loaded explicitly from a directory-based Anthropic-style `SKILL.md` package and attached to an `Agent` with `skills=[...]`.

```python
import os
from masfactory import Agent, OpenAIModel, ParagraphMessageFormatter, load_skill

model = OpenAIModel(
    api_key=os.getenv("OPENAI_API_KEY", ""),
    model_name=os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
)

paper_summary = load_skill("./skills/paper-summary")

agent = Agent(
    name="researcher",
    instructions="You are a research assistant.",
    model=model,
    formatters=ParagraphMessageFormatter(),
    skills=[paper_summary],
)
```

Example skill package:

```text
skills/
└── paper-summary/
    ├── SKILL.md
    ├── template.md
    └── examples/
        └── sample.md
```

`SKILL.md`:

```md
---
name: paper-summary
description: Summarize research papers clearly
---
Focus on the paper's problem, method, findings, and limitations.
Keep the summary concise and faithful.
```

## 🌟 Application Demo

Below are three example applications built with MASFactory for common agentic workflow scenarios: a daily AI paper briefing, a paper-to-PPT workflow, and a visual skill-building studio. The workflow code behind these products is open-sourced in this repository for reuse and study.

### NowWhat

**NowWhat** stands for "Now what are my peers working on?" It is an information-filtering app for AI researchers and developers. The service turns a daily stream of AI papers into a structured briefing, helping users quickly understand which papers are worth reading and what signals matter most.

- Hosted experience: https://what.masfactory.dev

<p align="center">
  <img src="applications/nowwhat/assets/nowwhat-preview-en.png" alt="NowWhat English product preview" width="980" />
</p>

### OhNoPPT

**OhNoPPT** is a **Paper2PPT** application for research-paper presentations. Users upload a paper and describe the presentation goal, and MASFactory orchestrates the full process from paper understanding to deck generation. Unlike many slide-generation tools that stop at static exports, OhNoPPT delivers a genuinely editable `.pptx` file.

- Hosted experience: https://ppt.masfactory.dev

<p align="center">
  <img src="applications/ohnoppt/assets/ohnoppt-preview-en.png" alt="OhNoPPT English product preview" width="980" />
</p>

### ClawCanvas

**ClawCanvas** is a visual skill studio for designing, testing, and packaging MASFactory workflows as reusable skills. Users can build an agent workflow on a web canvas, validate the graph structure, run supported nodes through MASFactory, and export the workflow together with skill metadata as a publishable skill package.

- Hosted experience: https://clawcanvas.masfactory.dev
- Application code: `applications/clawcanvas/`

<p align="center">
  <img src="applications/clawcanvas/assets/clawcanvas-preview-en.png" alt="ClawCanvas English product preview" width="980" />
</p>

## ▶️ Run the Multi-Agent Reproductions in This Repo (`applications/`)

Most workflows require `OPENAI_API_KEY`. Some scripts also read `OPENAI_BASE_URL` / `BASE_URL` and `OPENAI_MODEL_NAME`.

```bash
# ChatDev
python -m applications.chatdev.workflow.main --task "Develop a basic Gomoku game." --name "Gomoku"

# ChatDev Lite (simplified)
python -m applications.chatdev_lite.workflow.main --task "Develop a basic Gomoku game." --name "Gomoku"

# ChatDev Lite (VibeGraphing version)
python -m applications.chatdev_lite_vibegraph.main --task "Write a Ping-Pong (Pong) game." --name "PingPong"

# VibeGraph Demo (intent -> AML -> compile -> run)
python -m applications.vibegraph_demo.main

# AgentVerse · PythonCalculator
python applications/agentverse/tasksolving/pythoncalculator/run.py --task "write a simple calculator GUI using Python3."

# CAMEL role-playing demo
python applications/camel/main.py "Create a sample adder by using python"
```

## 📚 Learning Index

Documentation: https://docs.masfactory.dev/

- Quick Start: Introduction → Installation → Visualizer → First Code
- Progressive Tutorials: ChatDev Lite (Declarative / Imperative / VibeGraph)
- Development Guide: Core Concepts → Message Passing → NodeTemplate → Agent Runtime → Context Adapters (Memory / RAG / MCP) → Visualizer → Model Adapters

## 🗂️ Project Structure

```text
.
├── masfactory/                       # MASFactory framework
│   ├── core/                         # Core primitives: Node / Edge / Gate / MessageFormatter
│   ├── components/                   # Main workflow components
│   │   ├── agents/                   # Agent / DynamicAgent / SingleAgent
│   │   ├── controls/                 # LogicSwitch / AgentSwitch
│   │   ├── graphs/                   # Graph / RootGraph / Loop
│   │   ├── human/                    # Human-in-the-loop nodes
│   │   ├── composed_graph/           # Composite components
│   │   └── vibe/                     # Vibe Graphing
│   ├── adapters/                     # Model / Memory / Retrieval / MCP adapters
│   ├── integrations/                 # Third-party integrations
│   ├── utils/                        # Utilities
│   └── visualizer/                   # Runtime bridge for MASFactory Visualizer
├── masfactory-visualizer/            # VS Code extension: MASFactory Visualizer
├── applications/                     # Example and reproduction apps
│   ├── chatdev/
│   ├── chatdev_lite/
│   ├── chatdev_lite_vibegraph/
│   ├── agentverse/
│   ├── camel/
│   ├── clawcanvas/
│   ├── hugggpt2/
│   ├── metagpt/
│   ├── nowwhat/
│   ├── ohnoppt/
│   └── vibegraph_demo/
├── docs/                             # VitePress documentation site
├── README.md
├── README.zh.md
├── pyproject.toml
├── requirements.txt
└── uv.lock
```

## 📄 Citation

```bibtex
@article{liu2026masfactory,
  title   = {MASFactory: A Graph-centric Framework for Orchestrating LLM-Based Multi-Agent Systems with Vibe Graphing},
  author  = {Yang Liu and Jinxuan Cai and Yishen Li and Qi Meng and Zedi Liu and Xin Li and Chen Qian and Chuan Shi and Cheng Yang},
  journal = {arXiv preprint arXiv:2603.06007},
  year    = {2026},
  doi     = {10.48550/arXiv.2603.06007},
  url     = {https://arxiv.org/abs/2603.06007}
}
```

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=BUPT-GAMMA/MASFactory&type=Date)](https://star-history.com/#BUPT-GAMMA/MASFactory&Date)

## 📬 Contact
QQ: 2157069383

Discord: https://discord.gg/RWRYhWq7
