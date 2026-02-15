# VibeGraph Demo

This demo showcases how to use a single `VibeGraph` node to fully reproduce a ChatDev-style multi-agent software development workflow. Instead of manually coding each phase (demand analysis, language selection, coding, testing, etc.), you simply provide natural-language **build instructions** in `assets/build.txt`, and `VibeGraph` automatically generates and compiles the entire workflow graph at runtime.

## Upstream Reference

- Upstream repository (workflow inspiration): `https://github.com/OpenBMB/ChatDev`

## Layout

```
applications/vibegraph_demo/
├── assets/
│   ├── build.txt                # Build instructions (natural-language workflow description)
│   └── cache/
│       └── graph_design.json    # Cached graph design (auto-generated)
├── main.py                      # Entry point
└── README.md
```

## Setup

Run from the repo root:

```bash
uv sync

export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_MODEL_NAME="gpt-4o-mini"
```

## Run

```bash
uv run python applications/vibegraph_demo/main.py --model gpt-4o-mini
```

### CLI Arguments

| Argument | Default | Description |
|---|---|---|
| `--model` | `gpt-4o-mini` | Model used for invoke (running the compiled agents) |
| `--api_key` | `$OPENAI_API_KEY` | API key for invoke model |
| `--base_url` | `$OPENAI_BASE_URL` | Base URL for invoke model |
| `--build_model` | same as `--model` | Model used for build (generating the graph design) |
| `--build_api_key` | same as `--api_key` | API key for build model |
| `--build_base_url` | same as `--base_url` | Base URL for build model |

### Using a Different Build Model

If you want to use a more capable model for graph design generation while keeping a lighter model for execution:

```bash
uv run python applications/vibegraph_demo/main.py \
  --model gpt-4o-mini \
  --build_model gpt-4o
```

## How It Works

1. **Read build instructions** — Loads `assets/build.txt` which contains a detailed natural-language description of the desired workflow (agents, phases, tools, etc.)
2. **Build** — `VibeGraph` invokes the build workflow with these instructions to produce a `graph_design` JSON, then caches it to `assets/cache/graph_design.json`
3. **Compile** — The graph design is compiled into runnable nodes and edges on the fly
4. **Invoke** — The compiled graph executes the full ChatDev pipeline

On subsequent runs, if `assets/cache/graph_design.json` already exists, the build step is skipped and the cached design is loaded directly.

## Customization

To design a different workflow, edit `assets/build.txt` with your own instructions, then delete `assets/cache/graph_design.json` to force regeneration:

```bash
rm -f applications/vibegraph_demo/assets/cache/graph_design.json
uv run python applications/vibegraph_demo/main.py
```
