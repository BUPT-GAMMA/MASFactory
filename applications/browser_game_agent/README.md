# Browser Game Agent

A full-stack web application where an AI multi-agent pipeline automatically designs, codes, tests, and deploys browser games based on user descriptions.

## Features

- **AI Pipeline**: Planning → Coding → Documentation → UI Testing → Functional Testing → Fix
- **Tool-Grounded QA**: Static HTML/JS checks plus optional Playwright browser smoke tests before LLM judgement
- **Real-time Progress**: WebSocket streaming of pipeline stages
- **Live Game Preview**: Generated HTML5/Canvas games displayed in an iframe
- **Modification Mode**: Request changes and the agent re-codes, re-tests, and redeploys
- **Asking Mode**: Ask questions about the game mechanics or code without redeploying

## Tech Stack

- **Backend**: FastAPI + Python
- **Frontend**: Vanilla HTML/CSS/JS (no build step)
- **AI Pipeline**: MASFactory (RootGraph, Loop, LogicSwitch, InstructorAssistantGraph, optional HumanChatVisual)
- **Testing**: Python validators + optional Playwright/Chromium smoke tests
- **Model**: OpenAI-compatible API (gpt-4o-mini by default)

## Running


```bash
# App dependencies
pip install -r applications/browser_game_agent/requirements.txt
python -m playwright install chromium

# Using venv
.venv/bin/python applications/browser_game_agent/server/app.py

# Or with uvicorn for reload
.venv/bin/uvicorn applications.browser_game_agent.server.app:app --reload --port 8765
```

Open http://localhost:8765 in your browser.

Optional MASFactory/Human review:

```bash
# Enables MASFactory Visualizer-backed design review and diff confirmation
export BGA_ENABLE_HUMAN_REVIEW=1
```

When human review is enabled, modifications that overwrite existing files create a draft
and ask for `APPROVE` in MASFactory Visualizer before replacing the original file.

## Directory Structure

```
browser_game_agent/
├── assets/
│   ├── config/
│   │   ├── PhaseConfig.json    # Agent prompts for each phase
│   │   └── RoleConfig.json     # Agent role descriptions
│   └── output/games/           # Generated game files (one dir per session)
├── components/
│   ├── phases.py               # MASFactory phase classes
│   └── tools.py                # Game tools (save files, validate code)
├── workflow/
│   ├── pipeline.py             # Pipeline builder (generate/modify/ask)
│   └── utils.py                # Config loading utilities
└── server/
    ├── app.py                  # FastAPI server
    └── static/                 # Frontend (index.html, style.css, app.js)
```

## Pipeline Stages

| Stage | Agents | Output |
|-------|--------|--------|
| Planning | Game Designer + CEO | `game_plan` |
| Coding | Programmer + CTO | `index.html` |
| Documentation | Programmer + CPO | `README.md` |
| UI Test | QA Engineer + CTO | HTML/browser evidence report |
| Functional Test | QA Engineer + Programmer | JS/browser/checkpoint report |
| Fix (if needed) | Programmer + CTO | Updated `index.html` |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Frontend UI |
| `POST` | `/api/generate` | Start generation pipeline |
| `GET` | `/api/status/{id}` | Get session status |
| `WS` | `/ws/{id}` | Stream pipeline progress |
| `POST` | `/api/modify/{id}` | Trigger modification |
| `POST` | `/api/ask/{id}` | Ask about the game |
| `GET` | `/games/{id}/` | Serve generated game |
