# CAMEL (MASFactory Port)

This directory contains a MASFactory-based **CAMEL role-playing** workflow: an “AI User” and an “AI Assistant” collaborate through multi-turn conversation to solve a task via role-based prompting.

It also includes a set of evaluation scripts and utilities for common benchmarks (e.g., GAIA / GPQA / MMLU-Pro / MBPP / HumanEval / LiveCodeBench / BigCodeBench).

## Upstream Reference

- Upstream repository: `https://github.com/camel-ai/camel`

## Layout

```
applications/camel/
├── main.py                 # Entry point (CLI)
├── workflow.py             # Graph builder (role-playing workflow)
├── conversation_loop.py    # Core conversation loop
├── prompts.py              # Prompts / role definitions
├── result_writer.py        # Save results
├── eval/                   # Evaluation helpers (HumanEval, etc.)
├── gaia/                   # GAIA evaluation
├── gpqa/                   # GPQA evaluation
├── mmlu-pro/               # MMLU-Pro evaluation
├── mbpp/                   # MBPP evaluation
├── livecodebench/          # LiveCodeBench evaluation
├── bigcodebench/           # BigCodeBench evaluation
└── commongen/              # CommonGen evaluation
```

## Setup

Run from the repo root:

```bash
uv sync

export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_MODEL_NAME="gpt-4o-mini"
```

## Run (role-playing demo)

```bash
uv run python applications/camel/main.py "Create a simple adder in Python."
```
