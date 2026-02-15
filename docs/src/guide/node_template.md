# NodeTemplate (Templates, Scopes, and Dependency Lifecycles)

`NodeTemplate` is MASFactory’s core mechanism for **reusing node configuration** in declarative graphs.
It captures a node constructor (for example, `Agent`, `Loop`, `Switch`, or a subgraph) plus its keyword arguments as a reusable template, and the graph **materializes** templates into concrete node instances during assembly.

This page covers:

- What `NodeTemplate` is and the recommended usage pattern
- How to control dependency lifecycles with `Shared` / `Factory`
- The semantics, precedence, and typical scenarios of the four `template_*` scope functions

---

## 1) What NodeTemplate is

`NodeTemplate(NodeCls, **kwargs)` is **not** a node instance; it is a *declarative configuration template* with two key characteristics:

1. **Reusable**: the same template can be used across multiple graphs and subgraphs.
2. **Derivable**: you can override a small set of arguments to derive a new template.

Typical declarative usage:

```python
from masfactory import RootGraph, Agent, OpenAIModel, NodeTemplate

model = OpenAIModel(model_name="gpt-4o-mini", api_key="...", base_url="...")

BaseAgent = NodeTemplate(Agent, model=model)

g = RootGraph(
    name="demo",
    nodes=[
        ("assistant", BaseAgent(instructions="You are the Assistant.", prompt_template="Input: {x}")),
        ("instructor", BaseAgent(instructions="You are the Instructor.", prompt_template="Input: {x}\nDraft: {draft}")),
    ],
    edges=[
        ("ENTRY", "assistant", {"x": "input"}),
        ("assistant", "instructor", {"x": "input", "draft": "draft"}),
        ("instructor", "EXIT", {"plan": "final plan"}),
    ],
)

g.build()
```

### Important constraints

- `NodeTemplate(...)` does **not** create node instances directly.
- Node names are decided by the graph at assembly time:
  - Declarative: `nodes=[("name", template), ...]`
  - Imperative: `g.create_node(template, name="...")`
- `NodeTemplate(...)` accepts **keyword arguments only**, and it does not accept `name=` (node names are not part of templates).

---

## 2) Shared / Factory: controlling dependency lifecycles

`NodeTemplate` aims to avoid accidental sharing of mutable objects (for example, `dict/list/set`) across node instances.
When you inject runtime resources (HTTP clients, connection pools, locks, database handles, etc.), you should make lifecycles explicit:

- `Shared(obj)`: force sharing the **same instance** across materializations (suitable for stateless or thread-safe resources).
- `Factory(lambda: ...)`: create a **new instance per node** (suitable for stateful resources that must be isolated).

### Example: share the model, isolate the memory

```python
from masfactory import Agent, NodeTemplate, OpenAIModel
from masfactory.core.node_template import Shared, Factory
from masfactory.adapters.memory import HistoryMemory

model = OpenAIModel(model_name="gpt-4o-mini", api_key="...", base_url="...")

BaseAgent = NodeTemplate(
    Agent,
    model=Shared(model),
    # each Agent node gets an independent chat history
    memories=[Factory(lambda: HistoryMemory(top_k=100, memory_size=10000))],
)
```

Note: some framework types may be marked as shared by default via `__node_template_scope__ = "shared"`.
For non-framework objects, prefer `Shared/Factory` to keep lifecycles explicit.

---

## 3) `template_*`: assembly-time defaults and overrides

When you need to inject/override parameters **in bulk** (especially for nodes nested inside subgraphs), MASFactory provides four `template_*` scope functions (all are context managers):

- `template_defaults(**kwargs)`: fill global defaults **only when the template does not provide the value**.
- `template_overrides(**kwargs)`: force global overrides **even if the template explicitly provides the value**.
- `template_defaults_for(selector..., **kwargs)`: fill defaults for matched templates (selected by name/type).
- `template_overrides_for(selector..., **kwargs)`: force overrides for matched templates (selected by name/type).

These scopes apply **only during NodeTemplate materialization**, so they must wrap the code that triggers materialization:

- Declarative graphs: wrap `g.build()` (materialization happens during assembly).
- Imperative graphs: wrap `g.create_node(template, name=...)` (materialization happens at creation time).

---

## 4) Selector semantics and limitations

`template_defaults_for / template_overrides_for` selects **NodeTemplate declarations**, not runtime instances.
Matching has two parts:

- `selector`: matches the declaration **name** and **class**
- `path_filter` (optional): further scopes the match by the node **creation path**, which helps disambiguate nested nodes with the same name.

### selector: matches declaration info (name + class)

Selectors operate on *declarations* and do not depend on runtime objects:

- `type_filter` uses `issubclass` semantics.
- `name_filter` is an exact match by default (case-sensitive); for richer rules, pass a callable or a regex-like object.
- `predicate` receives `SelectionTarget(name, cls, obj=None)`. In NodeTemplate materialization, `obj` is always `None`.

### path_filter: scope by creation path

`path_filter` matches the node creation path:

`root_graph > ... > owner_graph > node_name`

Syntax: `segment > segment > ...`, where `segment` is either:

- a concrete name (letters/digits/`_`/`-` only)
- `*` to match exactly one segment
- `**` to match zero or more segments

Matching is “anywhere” by default (the implementation implicitly wraps the pattern with `**`), so you typically only need the most distinctive slice.

Examples:

- Override every nested `instructor`: `name_filter="instructor"`
- Override only the `instructor` inside `demand_analysis`: `path_filter="demand_analysis>instructor"`

---

## 5) Precedence (lowest → highest)

The assembly-time application order is:

1. `template_defaults_for(...)` (matched defaults; later scopes win)
2. `template_defaults(...)` (global defaults)
3. `template_overrides(...)` (global overrides)
4. `template_overrides_for(...)` (matched overrides)

Defaults apply only when a field is missing; overrides always win.

---

## 6) Typical use: overriding nested nodes without changing the template

The example below shows three scenarios:

1. Enhance all `instructor` agents without modifying the phase template.
2. Override only one nested `instructor` via `path_filter` (without renaming).
3. Override `phase_instructions` for a specific phase by phase node name.

```python
from masfactory import RootGraph, Loop, Agent, NodeTemplate
from masfactory.core.node_template import template_defaults_for, template_overrides_for

Phase = NodeTemplate(
    Loop,
    nodes=[
        ("assistant", NodeTemplate(Agent)),
        ("instructor", NodeTemplate(Agent)),
    ],
    edges=[
        ("CONTROLLER", "assistant", {"workspace": ""}),
        ("assistant", "instructor", {"workspace": ""}),
        ("instructor", "CONTROLLER", {"workspace": ""}),
    ],
)

g = RootGraph(
    name="demo",
    nodes=[
        ("demand_analysis", Phase),
        ("coding", Phase),
    ],
    edges=[
        ("ENTRY", "demand_analysis", {"workspace": ""}),
        ("demand_analysis", "coding", {"workspace": ""}),
        ("coding", "EXIT", {"workspace": ""}),
    ],
)

with (
    template_defaults_for(type_filter=Agent, hide_unused_fields=True),
    template_overrides_for(
        type_filter=Agent,
        name_filter="instructor",
        instructions="You are the Instructor. Review strictly and fill in missing risks and constraints.",
    ),
    template_overrides_for(
        type_filter=Agent,
        name_filter="instructor",
        path_filter="demand_analysis>instructor",
        instructions="You are the Instructor. Use a stricter bar and provide verifiable acceptance criteria and a risk list.",
    ),
    template_overrides_for(
        type_filter=Loop,
        name_filter="demand_analysis",
        attributes={"phase_instructions": "Demand analysis: clarify goals and constraints."},
    ),
):
    g.build()
```

---

## 7) Relationship to imperative graphs

`template_*` scopes affect **NodeTemplate materialization only**:

- If you use `g.create_node(Agent, ...)` (passing the class), `template_*` does not apply.
- If you use `g.create_node(BaseAgentTemplate, name="...")` (passing a template), `template_*` applies during that creation.
- Declarative graphs typically materialize in `build()`, which is why `template_*` is especially useful there.
