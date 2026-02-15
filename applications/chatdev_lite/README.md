# ChatDev Lite (MASFactory Port)

This directory contains a MASFactory-based **ChatDev Lite** workflow: a cleaner and more maintainable “multi-role software development” pipeline inspired by ChatDev, implemented via MASFactory’s phase abstractions (and `InstructorAssistantGraph` under the hood).

## Upstream Reference

- Upstream repository: `https://github.com/OpenBMB/ChatDev`

## Layout

```
applications/chatdev_lite/
├── assets/
│   ├── config/                         # ChatDev Lite configs (chain / phase prompts / role prompts)
│   │   ├── ChatChainConfig.json
│   │   ├── PhaseConfig.json
│   │   └── RoleConfig.json
│   └── output/
│       └── WareHouse/                  # Run outputs (one project folder per run)
├── chatdev/                             # Helpers (code/doc managers, utilities)
│   ├── codes.py
│   ├── documents.py
│   └── utils.py
├── components/
│   ├── lite_phase.py                    # LitePhase built on InstructorAssistantGraph
│   ├── tools.py                         # Phase tools (save code, run tests, write docs, etc.)
│   └── handlers.py                      # Misc helpers
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
uv run python applications/chatdev_lite/workflow/main.py \
  --task "Develop a basic Gomoku game." \
  --name "Gomoku" \
  --org "DefaultOrganization" \
  --model "${OPENAI_MODEL_NAME:-gpt-4o-mini}"
```

Outputs are written to `applications/chatdev_lite/assets/output/WareHouse/<project>_<org>_<timestamp>/`.
