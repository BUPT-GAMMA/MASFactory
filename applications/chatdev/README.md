# ChatDev (MASFactory Port)

This directory contains a MASFactory-based port of **ChatDev**: a multi-agent software development workflow that goes through demand analysis, language selection, coding, review, testing/fixing, and finally produces environment docs and a user manual.

## Upstream Reference

- Upstream repository: `https://github.com/OpenBMB/ChatDev`

## Layout

```
applications/chatdev/
├── assets/
│   ├── config/                         # ChatDev configs (chain / phase prompts / role prompts)
│   │   ├── ChatChainConfig.json
│   │   ├── PhaseConfig.json
│   │   └── RoleConfig.json
│   └── output/
│       └── WareHouse/                  # Run outputs (one project folder per run)
├── chatdev/                             # Helpers (code/doc managers, utilities)
│   ├── codes.py
│   ├── documents.py
│   └── utils.py
├── components/                          # Phase + composed-phase node implementations
│   ├── composed_phase.py
│   └── phase/
│       ├── phase.py
│       └── handlers.py
└── workflow/
    ├── main.py                          # Entry: build + invoke RootGraph
    ├── handlers.py                      # pre/post processing (workspace, meta, log move, etc.)
    └── utils.py                         # load configs & assemble attributes
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
uv run python applications/chatdev/workflow/main.py \
  --task "Develop a basic Gomoku game." \
  --name "Gomoku" \
  --org "DefaultOrganization" \
  --model "${OPENAI_MODEL_NAME:-gpt-4o-mini}"
```

Outputs are written to `applications/chatdev/assets/output/WareHouse/<project>_<org>_<timestamp>/`.
