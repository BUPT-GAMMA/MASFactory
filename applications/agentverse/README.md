# AgentVerse (MASFactory Port)

This directory contains a MASFactory-based port of AgentVerse multi-agent workflows. It covers:

- `tasksolving/`: iterative task solving (Role Assigner -> Decision Maker -> optional Executor -> Evaluator)
- `simulation/` / `simulations/`: multi-agent dialogue simulations (classroom, prisoner's dilemma, etc.)

All paths are standardized under `applications/agentverse/...`.

## Upstream Reference

- Upstream repository: `https://github.com/OpenBMB/AgentVerse`
- Reference paths (upstream): `agentverse/tasks/tasksolving/*`, `agentverse/tasks/simulation/*`

## Layout

```
applications/agentverse/
├── assets/                      # configs/data/output (data/output should be gitignored)
│   ├── configs/                 # YAML configs (used by some workflows)
│   ├── data/                    # datasets (HumanEval / SRDD / BigCodeBench / GAIA attachments, etc.)
│   └── output/                  # run outputs (should not be committed)
├── components/                  # reusable components (decision graphs, pipelines, executors, etc.)
├── tasksolving/                 # task reproductions
├── simulation/                  # simulations with `run.py` entry points
├── simulations/                 # alternative simulation implementations (directly runnable)
├── formatters.py                # output parsing/formatting helpers
└── utils.py                     # debug hooks and small utilities
```

## Setup

Run from the repo root:

```bash
uv sync

export OPENAI_API_KEY="..."
# Use either one (different scripts read different names).
export OPENAI_BASE_URL="https://api.apiyi.com/v1/"
# export BASE_URL="https://api.apiyi.com/v1/"

export MODEL_NAME="gpt-4o-mini"
```

Notes:

- Some scripts mention `.env.sh`; you can `source .env.sh` (see `.env.sh.example` in the repo root).
- The GAIA workflow additionally supports `TOOL_OPENAI_API_KEY` / `TOOL_OPENAI_BASE_URL` (see below).

## Run TaskSolving (per task)

Commands below assume the repo root as the working directory.
For any script that supports `--output-dir`, prefer setting it explicitly under `applications/agentverse/assets/output/...`.

### 1) brainstorming

```bash
uv run python applications/agentverse/tasksolving/brainstorming/run.py \
  --task "How to improve retrieval quality in long-context RAG?" \
  --model "${MODEL_NAME:-gpt-4o-mini}" \
  --max-turn 3 --max-inner-turns 0 --num-critics 4
```

### 2) pythoncalculator

```bash
uv run python applications/agentverse/tasksolving/pythoncalculator/run.py \
  --task "Write a simple calculator GUI using Python3." \
  --model "${MODEL_NAME:-gpt-4o-mini}" \
  --max-turn 3 --max-inner-turns 2 --num-critics 3 \
  --output-dir applications/agentverse/assets/output/pythoncalculator
```

### 3) commongen (single sample)

```bash
uv run python applications/agentverse/tasksolving/commongen/run.py \
  --task "dog, park, run, happy" \
  --model "${MODEL_NAME:-gpt-4o-mini}" \
  --max-turn 3 --num-critics 2 --max-inner-turns 3
```

### 4) logic_grid

```bash
uv run python applications/agentverse/tasksolving/logic_grid/workflow/run.py \
  --task "Five people each own a unique pet and drink..." \
  --model "${MODEL_NAME:-gpt-4o-mini}" \
  --max-turn 3 --num-critics 2 --max-inner-turns 3
```

### 5) mgsm

```bash
uv run python applications/agentverse/tasksolving/mgsm/run.py \
  --task "Tom has 3 apples and buys 4 more. How many apples does he have?" \
  --model "${MODEL_NAME:-gpt-4o-mini}" \
  --max-turn 3 --num-critics 2 --max-inner-turns 3 \
  --output-dir applications/agentverse/assets/output/mgsm
```

### 6) responsegen

```bash
uv run python applications/agentverse/tasksolving/responsegen/run.py \
  --task "User: I forgot my password. Agent: ..." \
  --model "${MODEL_NAME:-gpt-4o-mini}" \
  --max-turn 3 --num-critics 2 --max-inner-turns 3
```

### 7) humaneval (code generation)

Single task (`--task_id` selects an index; `-1` runs all tasks):

```bash
uv run python applications/agentverse/tasksolving/humaneval/run.py \
  --config humaneval-gpt4.yaml \
  --task_file humaneval/test.jsonl \
  --task_id 0 \
  --output_file humaneval
```

Offline evaluation (evaluate a saved results file locally):

```bash
uv run python applications/agentverse/tasksolving/humaneval/test_humaneval.py --help
uv run python applications/agentverse/tasksolving/humaneval/evaluate_humaneval_results.py --help
```

## Other TaskSolving Workflows (workflow-only)

The following tasks provide `workflow.py` graph builders for reuse by evaluation scripts. They do not have a dedicated `run.py` wrapper.

Example invocation (using `gpqa_solve`):

```bash
uv run python - <<'PY'
import yaml
from pathlib import Path
from applications.agentverse.tasksolving.gpqa_solve.workflow import build_gpqa_graph

cfg = yaml.safe_load(Path("applications/agentverse/assets/configs/gpqa-gpt4o-mini.yaml").read_text(encoding="utf-8"))
g = build_gpqa_graph(cfg)
out, attrs = g.invoke({"task_description": "Question: ...\\nA) ...\\nB) ...\\nC) ...\\nD) ..."})
print(attrs.get("solution") or out)
PY
```

Available builders:

- `srdd_code_gen`: `applications/agentverse/tasksolving/srdd_code_gen/workflow.py` -> `build_srdd_code_gen_graph(config)`
- `big_code_bench_gen`: `applications/agentverse/tasksolving/big_code_bench_gen/workflow.py` -> `build_big_code_bench_gen_graph(config)`
  - Typically requires dataset-provided `test_code` and `entry_point` to trigger local unit tests.
- `gpqa_solve`: `applications/agentverse/tasksolving/gpqa_solve/workflow.py` -> `build_gpqa_graph(config)`
- `mmlu_pro_reasoning`: `applications/agentverse/tasksolving/mmlu_pro_reasoning/workflow.py` -> `build_mmlu_pro_graph(config)`
- `gaia_solve`: `applications/agentverse/tasksolving/gaia_solve/workflow.py` -> `build_gaia_graph(config)`
  - Tool functions are defined in `applications/agentverse/tasksolving/gaia_solve/tools.py` (`gaia_tool_functions()`).
  - The Executor supports `TOOL_OPENAI_API_KEY` / `TOOL_OPENAI_BASE_URL` to override tool-calling model settings.

## Run Simulations

### 1) NLP Classroom (3 players)

```bash
uv run python applications/agentverse/simulation/nlp_classroom_3players/run.py \
  --model "${MODEL_NAME:-gpt-4o-mini}" \
  --max-turns 10 \
  --output-dir applications/agentverse/assets/output/nlp_classroom_3players
```

### 2) NLP Classroom (9 players)

```bash
uv run python applications/agentverse/simulation/nlp_classroom_9players/run.py \
  --model "${MODEL_NAME:-gpt-4o-mini}" \
  --max-turns 30 \
  --output-dir applications/agentverse/assets/output/nlp_classroom_9players
```

### 3) Prisoner Dilemma

```bash
uv run python applications/agentverse/simulation/prisoner_dilemma/run.py \
  --model "${MODEL_NAME:-gpt-4o-mini}" \
  --max-turns 8
```

### 4) Alternative simulation implementations

```bash
uv run python applications/agentverse/simulations/classroom/classroom.py --model "${MODEL_NAME:-gpt-4o-mini}"
uv run python applications/agentverse/simulations/prisoner_dilemma/prisoner_dilemma.py --model "${MODEL_NAME:-gpt-4o-mini}"
```
