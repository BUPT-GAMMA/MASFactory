# VibeGraphing

This chapter explains MASFactory’s **VibeGraphing** workflow: generate a `graph_design.json` artifact from natural-language intent, then compile it into runnable MASFactory graphs.

<ThemedDiagram
  light="/imgs/tutorial/chatdev-lite/prog-vibe-pipeline-light.svg"
  dark="/imgs/tutorial/chatdev-lite/prog-vibe-pipeline-dark.svg"
  alt="VibeGraphing: intent → graph_design → compile → run"
/>

---

## Key objects

- **`VibeGraph`**: a `Graph`-like node responsible for:
  - generating or loading a `graph_design`,
  - compiling `graph_design` into runnable nodes/edges,
  - caching the design artifact for iteration.
- **`graph_design.json`**: a versionable, human-readable **intermediate representation (IR)** of the workflow structure.
- **Build workflow**: the workflow used to generate `graph_design` (default: `VibeWorkflow`). You can swap it with your own.
- **Compiler**: compiles `graph_design` into a real MASFactory graph (see `masfactory/components/vibe/compiler.py`).

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
    build_cache_path=Path("assets/cache/graph_design.json"),
)
```

Runtime behavior:

1. If `build_cache_path` does not exist: run the build workflow to generate `graph_design` and cache it.
2. If `build_cache_path` exists: load the cached design.
3. Compile `graph_design` into runnable nodes/edges inside this `VibeGraph` instance.
4. Execute like a normal `Graph`.

---

## The `graph_design` standard

The standard definition lives under the repository `graph_design/` directory. All future generation/parsing of `graph_design` should align with that standard.

The same standard is used by the Visualizer **Vibe** tab when previewing/editing `graph_design.json`.

---

## Working with Visualizer

Recommended workflow:

1. Run once to generate `graph_design.json`.
2. Open **MASFactory Visualizer** to preview the topology.
3. Edit and save in the **Vibe** tab if needed.
4. Go back to Python to validate compilation and runtime behavior.

---

## Custom build workflows

If you want the design generation process to better fit your domain (role assignment, phase design, human confirmation, etc.), you can:

- provide `VibeGraph(..., build_workflow=...)`, and
- implement your own “generate → preview → modify → confirm” loop.

The default build workflow lives under `masfactory/components/vibe/vibe_workflow`.

