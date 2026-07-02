# VibeGraphing

This chapter explains MASFactory’s **VibeGraphing** workflow: generate an AML workflow artifact from natural-language intent, then compile it into runnable MASFactory graphs.

<ThemedDiagram
  light="/imgs/tutorial/chatdev-lite/prog-vibe-pipeline-light.svg"
  dark="/imgs/tutorial/chatdev-lite/prog-vibe-pipeline-dark.svg"
  alt="VibeGraphing: intent → AML → compile → run"
/>

---

## Key objects

- **`VibeGraph`**: a `Graph`-like node responsible for:
  - generating or loading an AML workflow,
  - compiling AML into runnable nodes/edges,
  - caching the design artifact for iteration.
- **`.aml` cache**: a versionable, human-readable source artifact for the workflow structure.
- **Build workflow**: the workflow used to generate AML (default: `VibeWorkflow`). You can swap it with your own.
- **Compiler**: compiles AML into a real MASFactory graph (see `masfactory/aml/compiler.py`).
- **`LegacyVibeGraph`**: the explicit migration path for old `graph_design.json` workflows and caches.

---

## Typical usage

```python
from pathlib import Path
from masfactory import VibeGraph, NodeTemplate

Workflow = NodeTemplate(
    VibeGraph,
    invoke_model=invoke_model,
    build_model=build_model,
    build_instructions=build_instructions,
    build_cache_path=Path("assets/cache/workflow.aml"),
)
```

Runtime behavior:

1. If `build_cache_path` does not exist: run the build workflow to generate AML and cache it.
2. If `build_cache_path` exists: load the cached design.
3. Compile AML into runnable nodes/edges inside this `VibeGraph` instance.
4. Execute like a normal `Graph`.

---

## Working with Visualizer

Recommended workflow:

1. Run once to generate a `.aml` cache.
2. Open **MASFactory Visualizer** to preview the topology.
3. Edit and save in the **Vibe** tab if needed.
4. Go back to Python to validate compilation and runtime behavior.

---

## Custom build workflows

If you want the design generation process to better fit your domain (role assignment, phase design, human confirmation, etc.), you can:

- provide `VibeGraph(..., build_workflow=...)`, and
- implement your own “generate → preview → modify → confirm” loop.

Custom build workflows used by `VibeGraph` must return AML text. If you have an older workflow that returns graph-design JSON, run it through `LegacyVibeGraph` while migrating it to AML.

The default build workflow lives under `masfactory/components/vibe/vibe_workflow`.
