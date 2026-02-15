# ChatDev Lite (VibeGraph, MASFactory Port)

This directory contains a MASFactory-based **ChatDev Lite** workflow built with **VibeGraph**: each “phase” is a subgraph generated from a natural-language `build_instructions` file, compiled into runnable MASFactory graphs, then executed to produce a small software project.

Workflow phases:

- `DemandAnalysis` → decide product modality
- `LanguageChoose` → pick programming language
- `Coding` → generate runnable multi-file code
- `TestLoop` (`TestErrorSummary` → `TestModification`) → execute the generated code, summarize failures, and apply fixes (up to 3 iterations)

## Upstream Reference

- Upstream repository: `https://github.com/OpenBMB/ChatDev`

## Layout

```
applications/chatdev_lite_vibegraph/
├── main.py                              # Entry: build + invoke the workflow
├── workflow.py                           # RootGraph wiring (phases + test loop)
├── tools.py                              # Helpers (workdir init, save code, run tests, logging)
└── assets/
    ├── build_instructions/               # Per-phase VibeGraph build prompts (editable)
    │   ├── demand_analysis_phase.txt
    │   ├── language_choose_phase.txt
    │   ├── coding_phase.txt
    │   ├── test_error_summary_phase.txt
    │   └── test_modification_phase.txt
    ├── cache/
    │   └── graph_design/                 # Cached VibeGraph designs (human-editable JSON)
    │       ├── demand_analysis.graph_design.json
    │       ├── language_choose.graph_design.json
    │       ├── coding.graph_design.json
    │       ├── test_error_summary.graph_design.json
    │       ├── test_modification.graph_design.json
    │       └── graph.json
    ├── config/
    │   └── ChatChainConfig.json           # Background prompt (ChatDev-style)
    └── output/
        └── WareHouse/                    # Run outputs (one project folder per run)
```

## Setup

Run from the repo root:

```bash
uv sync

export OPENAI_API_KEY="..."
# Use either one (different entrypoints read different names).
export OPENAI_BASE_URL="https://api.openai.com/v1"
# export BASE_URL="https://api.openai.com/v1"

export OPENAI_MODEL_NAME="gpt-4o-mini"
```

## Run

```bash
uv run python applications/chatdev_lite_vibegraph/main.py \
  --task "Write a simple Pong game in Python with a GUI." \
  --name "PingPong" \
  --org "DefaultOrganization" \
  --model "${OPENAI_MODEL_NAME:-gpt-4o-mini}"
```

Outputs are written to `applications/chatdev_lite_vibegraph/assets/output/WareHouse/<project>_<org>_<timestamp>/`.

## `graph_design` (Human-in-the-loop)

VibeGraph builds each phase from a **`graph_design` JSON** artifact (nodes + edges + per-step instructions). This is the main “human interaction” surface for iterating on the workflow structure.

- Cached designs live in `applications/chatdev_lite_vibegraph/assets/cache/graph_design/*.graph_design.json` and are compiled directly on subsequent runs.
- If a cache file is missing, VibeGraph runs the build workflow to regenerate it; during this step you may be prompted to **review/edit the JSON** (via MASFactory Visualizer in VS Code if available, otherwise via CLI) and type `AGREE` to accept.
- After editing any `assets/build_instructions/*.txt`, delete the corresponding `*.graph_design.json` cache file to force a rebuild with your updated instructions.
