# MetaGPT (MASFactory Port)

This directory contains a MASFactory-based port of **MetaGPT**'s "software company" workflow: a multi-agent system that iterates through planning, implementation, testing, and integration to produce a complete project.

## Upstream Reference

- Upstream repository: `https://github.com/geekan/MetaGPT`

## Layout

```
applications/metagpt/
├── README.md
└── software_company/
    ├── __init__.py
    ├── components.py                 # Agent / node implementations
    ├── dev_loop.py                   # DevLoop: iterative dev + test/fix
    ├── run.py                        # Entry: run a single task
    ├── software_company.py           # RootGraph factory
    ├── tools.py                      # Workspace helper tools
    └── projects/                     # Run outputs (one folder per --name)
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
uv run python applications/metagpt/software_company/run.py \
  --task "Build a simple CLI TODO app in Python." \
  --name "todo_cli" \
  --phase full \
  --model "${OPENAI_MODEL_NAME:-gpt-4o-mini}"
```

Outputs are written to `applications/metagpt/software_company/projects/<name>/`.
