# VibeGraphing

This page provides a more complete `VibeGraph` example: generate AML, cache it, compile, and run.

<ThemedDiagram
  light="/imgs/tutorial/chatdev-lite/prog-vibe-pipeline-light.svg"
  dark="/imgs/tutorial/chatdev-lite/prog-vibe-pipeline-dark.svg"
  alt="VibeGraphing: intent → AML → compile → run"
/>

---

## Example: generate and run a linear workflow

```python
import os
from pathlib import Path

from masfactory import RootGraph, VibeGraph, NodeTemplate, OpenAIModel

model = OpenAIModel(
    model_name=os.getenv("MODEL", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
)

build_instructions = """
Build a linear AML workflow with 3 agent steps.
"""

Workflow = NodeTemplate(
    VibeGraph,
    invoke_model=model,
    build_model=model,
    build_instructions=build_instructions,
    build_cache_path=Path("assets/cache/example_workflow.aml"),
)

g = RootGraph(
    name="vibegraph_example",
    nodes=[("workflow", Workflow)],
    edges=[
        ("ENTRY", "workflow", {}),
        ("workflow", "EXIT", {}),
    ],
)

g.build()
g.invoke({})
```

---

## Iteration tips

- After the first run, inspect `assets/cache/example_workflow.aml`.
- Use Visualizer (Vibe tab) to preview/edit the structure.
- Save changes and run again to validate compilation and runtime behavior.
