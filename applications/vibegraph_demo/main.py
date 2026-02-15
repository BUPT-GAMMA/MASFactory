from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from masfactory import OpenAIModel, RootGraph, VibeGraph


parser = argparse.ArgumentParser(description="VibeGraph Demo")
parser.add_argument("--model", type=str, default="gpt-4o-mini", help="Model name")
parser.add_argument("--api_key", type=str, default=None, help="OpenAI API key")
parser.add_argument("--base_url", type=str, default=None, help="OpenAI API base URL")
parser.add_argument("--build_model", type=str, default="gpt-5.2", help="Build model name (defaults to --model)")
parser.add_argument("--build_api_key", type=str, default=None, help="Build model API key (defaults to --api_key)")
parser.add_argument("--build_base_url", type=str, default=None, help="Build model base URL (defaults to --base_url)")
args = parser.parse_args()
model_name = args.model or "gpt-4o-mini"
base_url = args.base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL")
api_key = args.api_key or os.getenv("OPENAI_API_KEY")
if not api_key:
    raise SystemExit("Missing OpenAI API key: set OPENAI_API_KEY or pass --api_key")

model = OpenAIModel(model_name=model_name, api_key=api_key, base_url=base_url)
build_model_name = args.build_model or "gpt-5.2"
build_base_url = args.build_base_url or base_url 
build_api_key = args.build_api_key or api_key
build_model = OpenAIModel(
    model_name=build_model_name,
    api_key=build_api_key,
    base_url=build_base_url,
)
assets_dir = Path(__file__).resolve().parent / "assets"
build_instruction = (assets_dir / "build.txt").read_text(encoding="utf-8")
cache_path = str(assets_dir / "cache" / "graph_design.json")
(assets_dir / "cache").mkdir(parents=True, exist_ok=True)

graph = RootGraph(name="vibegraph_demo")

vibe = graph.create_node(
    VibeGraph,
    name="vibe_graph",
    invoke_model=model,
    build_instructions=build_instruction,
    build_model=build_model,
    build_cache_path=cache_path,
)

graph.edge_from_entry(receiver=vibe, keys={})
graph.edge_to_exit(sender=vibe, keys={})

graph.build()
graph.invoke(input={}, attributes={})
