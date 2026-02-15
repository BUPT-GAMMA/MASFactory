# HuggingGPT2 (MASFactory Port)

This directory contains a MASFactory-based reproduction of **HuggingGPT / JARVIS**: a system that plans a task into subtasks, selects suitable models/tools for each subtask, executes them, and then synthesizes a final response.

## Upstream Reference

- Upstream repository: `https://github.com/microsoft/JARVIS`

## Layout

```
applications/hugggpt2/
├── main.py                 # Entry point (CLI)
├── workflow.py             # Graph builder
├── config.yaml             # Runtime configuration (model routing, endpoints, logging)
├── prompts.py              # System prompts
├── adapters/               # Model/tool adapters (local / HuggingFace / selector)
├── components/             # Task parser / model chooser / executor / response generator
├── demos/                  # Demo assets
└── result_writer.py        # Save results
```

## Setup

Run from the repo root:

```bash
uv sync

export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_MODEL_NAME="gpt-4o-mini"

# Optional (for HuggingFace inference mode):
export HUGGINGFACE_ACCESS_TOKEN="..."
```

## Run

```bash
uv run python applications/hugggpt2/main.py \
  "Generate a small game with a UI, including images and runnable code." \
  --config applications/hugggpt2/config.yaml
```
