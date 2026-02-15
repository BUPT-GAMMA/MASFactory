# Imperative ChatDev Lite

This tutorial builds a simplified `ChatDev Lite` in an **imperative** style: create nodes and edges step by step (`create_node / create_edge`) until the final workflow matches the declarative version.

> Note: this page is “operations-first”. For the declarative version, see:  
> [Declarative ChatDev Lite](/progressive/chatdev_declarative).

> Convention (aligned with the declarative tutorial):
> - Step 1–Step 2 emphasize **edge key contracts** (horizontal message passing).
> - Starting from Step 3, important state is promoted into **RootGraph attributes** and synchronized via `pull_keys / push_keys`, reducing edge field wiring.

---

## Step 1 — Wiring a minimal phase (two agents)

Start from:

`ENTRY → instructor → assistant → EXIT`

<ThemedDiagram
  light="/imgs/tutorial/chatdev-lite/prog-01-workflow-en-light.svg"
  dark="/imgs/tutorial/chatdev-lite/prog-01-workflow-en-dark.svg"
  alt="Step 1: wiring a minimal phase (two agents)"
/>

```python
import os
from masfactory import RootGraph, Agent, OpenAIModel, HistoryMemory

model = OpenAIModel(
    model_name=os.getenv("MODEL", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
)

history = HistoryMemory(top_k=12)

g = RootGraph(name="p1_workflow_imp")

instructor = g.create_node(
    Agent,
    name="instructor",
    model=model,
    memories=[history],
    instructions="You are the Instructor. Read the user demand and guide the Assistant.\n",
    prompt_template="【USER DEMAND】\n{user_demand}\n\n",
)
assistant = g.create_node(
    Agent,
    name="assistant",
    model=model,
    memories=[history],
    instructions="You are the Assistant. Complete the task based on user demand and Instructor guidance.\n",
    prompt_template=(
        "【USER DEMAND】\n{user_demand}\n\n"
        "【INSTRUCTOR GUIDANCE】\n{instructor_guidance}\n\n"
    ),
)

g.edge_from_entry(instructor, {"user_demand": "user demand"})
g.create_edge(instructor, assistant, {"instructor_guidance": "Instructor guidance"})
g.edge_to_exit(assistant, {"assistant_response": "Assistant response"})

g.build()
message = {"user_demand": "Build a number guessing game."}
out, _attrs = g.invoke(message)
print(out["assistant_response"])
```

---

## Step 2 — Multi-turn collaboration with Loop (edge messages)

Wrap Step 1 into a loop to support multi-turn convergence.  
To demonstrate horizontal passing, we keep using edge keys inside the loop and iterate via `assistant_response` ↔ `instructor_guidance`.

<ThemedDiagram
  light="/imgs/tutorial/chatdev-lite/prog-04-loop-edge-en-light.svg"
  dark="/imgs/tutorial/chatdev-lite/prog-04-loop-edge-en-dark.svg"
  alt="Step 2: Loop + edge messages"
/>

```python
import os
from masfactory import RootGraph, Loop, Agent, OpenAIModel, HistoryMemory

model = OpenAIModel(
    model_name=os.getenv("MODEL", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
)

history = HistoryMemory(top_k=12)

g = RootGraph(name="p2_loop_edge_imp")

dialog = g.create_node(
    Loop,
    name="dialog",
    max_iterations=4,
    initial_messages={"assistant_response": "No assistant response yet."},
)

assistant = dialog.create_node(
    Agent,
    name="assistant",
    model=model,
    memories=[history],
    instructions="You are the Assistant. Complete the task based on user demand and Instructor guidance.",
    prompt_template=(
        "【USER DEMAND】\n{user_demand}\n\n"
        "【INSTRUCTOR GUIDANCE】\n{instructor_guidance}\n\n"
    ),
)
instructor = dialog.create_node(
    Agent,
    name="instructor",
    model=model,
    memories=[history],
    instructions="You are the Instructor. Read user demand and the previous assistant_response, then provide improvements.",
    prompt_template=[
        "【USER DEMAND】\n{user_demand}\n\n",
        "【ASSISTANT RESPONSE】\n{assistant_response}\n\n",
    ],
)

dialog.edge_from_controller(instructor, {"user_demand": "user demand", "assistant_response": "previous Assistant response"})
dialog.create_edge(instructor, assistant, {"instructor_guidance": "Instructor guidance"})
dialog.edge_to_controller(assistant, {"assistant_response": "Assistant response"})

g.edge_from_entry(dialog, {"user_demand": "user demand"})
g.edge_to_exit(dialog, {"assistant_response": "Assistant response"})

g.build()
message = {"user_demand": "Build a number guessing game."}
out, _attrs = g.invoke(message)
print(out["assistant_response"])
```

---

## Step 3 — Switch + pull/push: manual alternating assembly

Aligned with the declarative tutorial Step 3, we manually assemble an alternating structure with:

`Loop + LogicSwitch + 2 Agents`

Key points:

- `LogicSwitch` routes to `assistant` or `instructor` based on `current_iteration`.
- `task / draft / plan` live in **RootGraph attributes** and are synchronized via `pull_keys / push_keys`.
- Internal edges only carry control flow (`keys = {}`); field orchestration is handled by attributes.

<ThemedDiagram
  light="/imgs/tutorial/chatdev-lite/prog-05-switch-attr-en-light.svg"
  dark="/imgs/tutorial/chatdev-lite/prog-05-switch-attr-en-dark.svg"
  alt="Step 3: Switch + pull/push (imperative assembly)"
/>

```python
import os
from masfactory import RootGraph, Loop, LogicSwitch, Agent, OpenAIModel, HistoryMemory

model = OpenAIModel(
    model_name=os.getenv("MODEL", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
)

history = HistoryMemory(top_k=12)

g = RootGraph(
    name="p3_switch_attr_imp",
    attributes={"task": "Build a number guessing game.", "draft": "", "plan": ""},
)

assistant_first = True

def to_assistant(messages: dict, attributes: dict) -> bool:
    i = int(attributes.get("current_iteration", 0))
    return (i % 2 == 1) if assistant_first else (i % 2 == 0)

def to_instructor(messages: dict, attributes: dict) -> bool:
    return not to_assistant(messages, attributes)

phase = g.create_node(
    Loop,
    name="phase",
    max_iterations=4,
    pull_keys={"task": "", "draft": "", "plan": ""},
    push_keys={"draft": "", "plan": ""},
)

switch = phase.create_node(
    LogicSwitch,
    name="switch",
    routes={"assistant": to_assistant, "instructor": to_instructor},
)
assistant = phase.create_node(
    Agent,
    name="assistant",
    model=model,
    memories=[history],
    instructions=(
        "You are the Assistant (CPO). Improve the draft.\n"
        "Output requirement: JSON only, MUST include draft (str)."
    ),
    prompt_template=[
        "【Task】\n{task}\n\n",
        "【Current draft】\n{draft}\n\n",
        "Update draft (string).",
    ],
    pull_keys={"task": "", "draft": "", "plan": ""},
    push_keys={"draft": ""},
)
instructor = phase.create_node(
    Agent,
    name="instructor",
    model=model,
    memories=[history],
    instructions=(
        "You are the Instructor (CEO). Review the draft and produce an executable plan.\n"
        "Output requirement: JSON only, MUST include plan (str). You may also output draft (str) if needed."
    ),
    prompt_template=[
        "【Task】\n{task}\n\n",
        "【Draft】\n{draft}\n\n",
        "【Current plan】\n{plan}\n\n",
        "Update plan (string); revise draft if necessary.",
    ],
    pull_keys={"task": "", "draft": "", "plan": ""},
    push_keys={"plan": "", "draft": ""},
)

# Internal edges: control flow only (keys = {})
phase.edge_from_controller(switch, {})
phase.create_edge(switch, assistant, {})
phase.create_edge(switch, instructor, {})
phase.edge_to_controller(assistant, {})
phase.edge_to_controller(instructor, {})

g.edge_from_entry(phase, {})
g.edge_to_exit(phase, {})

g.build()
_out, out_attrs = g.invoke({})
print(out_attrs["plan"])
```

---

## Step 4 — Encapsulate as a composite component: Phase

In Step 3 we manually assembled `Loop + LogicSwitch + 2 Agents`.  
When you need to reuse this structure across multiple places, a more maintainable approach is to encapsulate it as a **composite component** (composed graph): it behaves like a reusable “atomic node”.

Below is a skeleton equivalent to the built-in `masfactory/components/composed_graph/instructor_assistant_graph.py`.  
To align naming with the declarative tutorial, we call it `Phase` here (semantically equivalent to `InstructorAssistantGraph`).

```python
from __future__ import annotations

from masfactory import Agent, LogicSwitch, Loop, OpenAIModel, HistoryMemory
from masfactory.adapters.model import Model
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook


class Phase(Loop):
    \"\"\"A reusable Instructor/Assistant alternating loop.\"\"\"

    def __init__(
        self,
        name: str,
        model: Model,
        max_turns: int,
        phase_instructions: str,
        instructor_instructions: str,
        assistant_instructions: str,
        instructor_first: bool = True,
        pull_keys: dict | None = None,
        push_keys: dict | None = None,
        attributes: dict | None = None,
    ):
        if attributes is None:
            attributes = {}
        super().__init__(
            name=name,
            max_iterations=max_turns,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes={**attributes, "phase_instructions": phase_instructions},
        )
        self._model = model
        self._instructor_instructions = instructor_instructions
        self._assistant_instructions = assistant_instructions
        self._instructor_first = instructor_first
        self._history = HistoryMemory(top_k=12)

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        def to_instructor(_messages: dict, attributes: dict) -> bool:
            i = int(attributes.get("current_iteration", 0))
            return (i % 2 == 1) if self._instructor_first else (i % 2 == 0)

        def to_assistant(messages: dict, attributes: dict) -> bool:
            return not to_instructor(messages, attributes)

        switch = self.create_node(
            LogicSwitch,
            name="switch",
            routes={"assistant": to_assistant, "instructor": to_instructor},
        )

        assistant = self.create_node(
            Agent,
            name="assistant",
            model=self._model,
            memories=[self._history],
            instructions=self._assistant_instructions,
            pull_keys=self._pull_keys,
            push_keys=self._push_keys,
        )
        instructor = self.create_node(
            Agent,
            name="instructor",
            model=self._model,
            memories=[self._history],
            instructions=self._instructor_instructions,
            pull_keys=self._pull_keys,
            push_keys=self._push_keys,
        )

        # Internal edges: control flow only (keys = {})
        self.edge_from_controller(switch, {})
        self.create_edge(switch, assistant, {})
        self.create_edge(switch, instructor, {})
        self.edge_to_controller(assistant, {})
        self.edge_to_controller(instructor, {})

        super().build()


# Usage: Phase behaves like a reusable node.
import os
from masfactory import RootGraph

model = OpenAIModel(
    model_name=os.getenv("MODEL", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
)
g = RootGraph(name="p4_phase_component", attributes={"task": "...", "draft": "", "plan": ""})
phase = g.create_node(
    Phase,
    name="phase",
    model=model,
    max_turns=4,
    phase_instructions="Single-phase convergence: produce draft and plan.",
    instructor_instructions="...",
    assistant_instructions="...",
    pull_keys={"task": "", "draft": "", "plan": ""},
    push_keys={"draft": "", "plan": ""},
)
g.edge_from_entry(phase, {})
g.edge_to_exit(phase, {})
g.build()
```

::: tip Note
In real projects, you usually do not need to implement `Phase` yourself. MASFactory provides an equivalent built-in component: `InstructorAssistantGraph`.
The next step uses that built-in component directly.
:::

---

## Step 5 — Use the built-in composite component: InstructorAssistantGraph

The manual assembly in Step 3 highlights the essential elements (Loop, Switch, pull/push).  
In practice, MASFactory provides `InstructorAssistantGraph` to reuse this structure and reduce assembly cost.

```python
import os
from masfactory import RootGraph, InstructorAssistantGraph, OpenAIModel

model = OpenAIModel(
    model_name=os.getenv("MODEL", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
)

g = RootGraph(
    name="p5_iagraph_imp",
    attributes={"task": "Build a number guessing game.", "draft": "", "plan": ""},
)

phase = g.create_node(
    InstructorAssistantGraph,
    name="phase",
    model=model,
    max_turns=4,
    instructor_role_name="Instructor",
    assistant_role_name="Assistant",
    phase_instructions="Single-phase convergence: produce draft and plan.",
    instructor_instructions=(
        "You are the Instructor (CEO). Review the draft and produce an executable plan.\n"
        "Output requirement: JSON only, MUST include plan (str). You may also output draft (str) if needed."
    ),
    assistant_instructions=(
        "You are the Assistant (CPO). Improve the draft.\n"
        "Output requirement: JSON only, MUST include draft (str)."
    ),
    assistant_prompt_template=[
        "【Task】\n{task}\n\n",
        "【Current draft】\n{draft}\n\n",
        "Update draft (string).",
    ],
    instructor_prompt_template=[
        "【Task】\n{task}\n\n",
        "【Draft】\n{draft}\n\n",
        "【Current plan】\n{plan}\n\n",
        "Update plan (string); revise draft if necessary.",
    ],
    pull_keys={"task": "", "draft": "", "plan": ""},
    push_keys={"draft": "", "plan": ""},
    # Internal edges carry control-flow only: avoid field wiring on in/out edges.
    assistant_in_keys={},
    assistant_out_keys={},
    instructor_in_keys={},
    instructor_out_keys={},
)

g.edge_from_entry(phase, {})
g.edge_to_exit(phase, {})

g.build()
_out, out_attrs = g.invoke({})
print(out_attrs["plan"])
```

---

## Step 6 — Assemble 6 phases with InstructorAssistantGraph (simplified ChatDev Lite)

Target topology:

`ENTRY → demand_analysis → language_choose → coding → code_complete → coding_test → manual → EXIT`

<ThemedDiagram
  light="/imgs/tutorial/chatdev-lite/prog-06-phases-en-light.svg"
  dark="/imgs/tutorial/chatdev-lite/prog-06-phases-en-dark.svg"
  alt="Step 6: chain 6 phases"
/>

This example is closer to `applications/chatdev_lite`: it reuses the repository **Role/Phase prompt configs** and keeps shared state in **RootGraph attributes** (phase-to-phase passing via pull/push).

```python
import json
import os
from pathlib import Path

from masfactory import RootGraph, InstructorAssistantGraph, OpenAIModel

# 1) Load ChatDev Lite prompt configs (from this repo)
CONFIG_DIR = Path("applications/chatdev_lite/assets/config")
role_config = json.loads((CONFIG_DIR / "RoleConfig.json").read_text(encoding="utf-8"))
phase_config = json.loads((CONFIG_DIR / "PhaseConfig.json").read_text(encoding="utf-8"))
chat_chain_config = json.loads((CONFIG_DIR / "ChatChainConfig.json").read_text(encoding="utf-8"))

def join_lines(v: list[str] | str | None) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return "\n".join(v)
    return str(v)

model = OpenAIModel(
    model_name=os.getenv("MODEL", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
)

# 2) RootGraph attributes: shared state (minimal subset for demo)
attrs = {
    "task": "Develop a basic Gomoku game.",
    "chatdev_prompt": chat_chain_config.get("background_prompt", ""),
    "description": "",
    "ideas": "",
    "modality": "",
    "language": "",
    "codes": [],
    "unimplemented_file": "",
    "exist_bugs_flag": True,
    "test_reports": "",
    "error_summary": "",
    "requirements": "",
    "manual": "",
}

g = RootGraph(name="chatdev_lite_simplified_imp", attributes=attrs)

def add_phase(*, node_name: str, phase_key: str, max_turns: int = 3):
    spec = phase_config[phase_key]
    assistant_role = spec["assistant_role_name"]
    instructor_role = spec["user_role_name"]

    assistant_instructions = join_lines(role_config[assistant_role])
    instructor_instructions = join_lines(role_config[instructor_role])

    phase_instructions = join_lines(spec["phase_prompt"])
    tool_instruction = join_lines(spec.get("tool_instruction"))
    if tool_instruction:
        assistant_instructions = tool_instruction + "\n" + assistant_instructions

    phase_pull = {
        "task": "",
        "description": "",
        "ideas": "",
        "modality": "",
        "language": "",
        "codes": "",
        "unimplemented_file": "",
        "exist_bugs_flag": "",
        "test_reports": "",
        "error_summary": "",
        "requirements": "",
        "manual": "",
        "chatdev_prompt": "",
        "gui": "",
        "directory": "",
    }
    phase_push = {
        "modality": "",
        "language": "",
        "codes": "",
        "unimplemented_file": "",
        "test_reports": "",
        "error_summary": "",
        "requirements": "",
        "manual": "",
    }

    return g.create_node(
        InstructorAssistantGraph,
        name=node_name,
        model=model,
        max_turns=max_turns,
        instructor_role_name=instructor_role,
        instructor_instructions=instructor_instructions,
        assistant_role_name=assistant_role,
        assistant_instructions=assistant_instructions,
        phase_instructions=phase_instructions,
        pull_keys=phase_pull,
        push_keys=phase_push,
    )

# 3) Chain 6 phases (simplified)
demand = add_phase(node_name="demand_analysis", phase_key="DemandAnalysis", max_turns=3)
lang = add_phase(node_name="language_choose", phase_key="LanguageChoose", max_turns=3)
coding = add_phase(node_name="coding", phase_key="Coding", max_turns=1)
complete = add_phase(node_name="code_complete", phase_key="CodeComplete", max_turns=3)
test = add_phase(node_name="coding_test", phase_key="TestErrorSummary", max_turns=1)
manual = add_phase(node_name="manual", phase_key="Manual", max_turns=1)

# Edges carry control flow only; phase state is passed via attributes.
g.edge_from_entry(demand, {})
g.create_edge(demand, lang, {})
g.create_edge(lang, coding, {})
g.create_edge(coding, complete, {})
g.create_edge(complete, test, {})
g.create_edge(test, manual, {})
g.edge_to_exit(manual, {})

g.build()
out, out_attrs = g.invoke({})
print("done, manual bytes:", len(str(out_attrs.get("manual", ""))))
```

::: tip Note
- This chapter is designed for quickly learning MASFactory’s imperative paradigm, so it omits some implementation details of ChatDev.
  For complete reproductions, refer to: [ChatDev-Lite](https://github.com/BUPT-GAMMA/MASFactory/tree/main/applications/chatdev_lite) or [ChatDev](https://github.com/BUPT-GAMMA/MASFactory/tree/main/applications/chatdev).
:::

