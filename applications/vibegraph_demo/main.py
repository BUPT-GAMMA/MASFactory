from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from applications.chatdev_lite_vibegraph.tools import (
    codes_check_and_processing_tool as _codes_check_and_processing_tool,
)
from applications.chatdev_lite_vibegraph.tools import run_tests_tool as _run_tests_tool
from masfactory import OpenAIModel, RootGraph, VibeGraph

DEFAULT_TASK = (
    "Write a Ping-Pong (Pong) game, use Python and ultimately provide an application that can be run directly."
)
APP_DIR = Path(__file__).resolve().parent
ASSETS_DIR = APP_DIR / "assets"
CACHE_PATH = ASSETS_DIR / "cache" / "workflow.aml"
BUILD_PATH = ASSETS_DIR / "build.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VibeGraph Demo")
    parser.add_argument("--task", type=str, default=DEFAULT_TASK, help="Task prompt for the generated workflow")
    parser.add_argument("--name", type=str, default="VibeGraphDemo", help="Project name for generated output")
    parser.add_argument("--org", type=str, default="DefaultOrganization", help="Organization name for generated output")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="Model name")
    parser.add_argument("--api_key", type=str, default=None, help="OpenAI API key")
    parser.add_argument("--base_url", type=str, default=None, help="OpenAI API base URL")
    parser.add_argument("--build_model", type=str, default=None, help="Build model name (defaults to --model)")
    parser.add_argument("--build_api_key", type=str, default=None, help="Build model API key (defaults to --api_key)")
    parser.add_argument("--build_base_url", type=str, default=None, help="Build model base URL (defaults to --base_url)")
    return parser.parse_args()



def _sanitize_segment(raw: object, fallback: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(raw or "").strip()).strip("_.-")
    return value or fallback



def _ensure_workdir(attributes: dict[str, object]) -> Path:
    directory_raw = attributes.get("work_dir") or attributes.get("directory")
    if isinstance(directory_raw, str) and directory_raw.strip():
        work_dir = Path(directory_raw.strip())
    else:
        start_time = str(attributes.get("start_time") or "").strip() or time.strftime("%Y%m%d%H%M%S", time.localtime())
        attributes["start_time"] = start_time
        project = _sanitize_segment(attributes.get("project_name") or attributes.get("name"), "VibeGraphDemo")
        org = _sanitize_segment(attributes.get("org_name") or attributes.get("org"), "DefaultOrganization")
        work_dir = ASSETS_DIR / "output" / "WareHouse" / f"{project}_{org}_{start_time}"

    work_dir.mkdir(parents=True, exist_ok=True)
    attributes["work_dir"] = str(work_dir)
    attributes["directory"] = str(work_dir)

    log_path_raw = attributes.get("log_filepath")
    if isinstance(log_path_raw, str) and log_path_raw.strip():
        log_path = Path(log_path_raw.strip())
        if not log_path.is_absolute():
            log_path = work_dir / log_path
    else:
        log_path = work_dir / "workflow.log"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    attributes["log_filepath"] = str(log_path)
    return work_dir



def build_demo_graph(*, model: OpenAIModel, build_model: OpenAIModel) -> RootGraph:
    build_instruction = BUILD_PATH.read_text(encoding="utf-8")
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    graph = RootGraph(name="vibegraph_demo")

    def _runtime_attributes() -> dict[str, object]:
        attributes = graph.attributes
        _ensure_workdir(attributes)
        return attributes

    def codes_check_and_processing_tool(codes: object) -> str:
        """Save generated code files into the demo work directory."""
        return _codes_check_and_processing_tool(codes, attributes=_runtime_attributes())

    def check_code_completeness_tool() -> str:
        """Report whether generated Python files still contain pass or NotImplementedError."""
        work_dir = _ensure_workdir(graph.attributes)
        unimplemented_file: str | None = None
        for path in sorted(work_dir.rglob("*.py")):
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                continue
            if "NotImplementedError" in content or re.search(r"(?m)^\s*pass\b", content):
                unimplemented_file = str(path.relative_to(work_dir)).replace("\\", "/")
                break

        payload = {
            "has_unimplemented": unimplemented_file is not None,
            "filename": unimplemented_file,
            "unimplemented_file": unimplemented_file,
        }
        return json.dumps(payload, ensure_ascii=False)

    def run_tests_tool() -> dict:
        """Run the generated application and return the test report plus bug flag."""
        return _run_tests_tool({}, _runtime_attributes())

    vibe = graph.create_node(
        VibeGraph,
        name="vibe_graph",
        invoke_model=model,
        build_instructions=build_instruction,
        build_model=build_model,
        build_cache_path=str(CACHE_PATH),
        invoke_tools=[
            codes_check_and_processing_tool,
            check_code_completeness_tool,
            run_tests_tool,
        ],
    )

    graph.edge_from_entry(receiver=vibe, keys={})
    graph.edge_to_exit(sender=vibe, keys={})
    return graph



def _build_models(args: argparse.Namespace) -> tuple[OpenAIModel, OpenAIModel]:
    model_name = args.model or "gpt-4o-mini"
    base_url = args.base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL")
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Missing OpenAI API key: set OPENAI_API_KEY or pass --api_key")

    model = OpenAIModel(model_name=model_name, api_key=api_key, base_url=base_url)
    build_model_name = args.build_model or model_name
    build_base_url = args.build_base_url or base_url
    build_api_key = args.build_api_key or api_key
    build_model = OpenAIModel(
        model_name=build_model_name,
        api_key=build_api_key,
        base_url=build_base_url,
    )
    return model, build_model



def main() -> None:
    args = parse_args()
    model, build_model = _build_models(args)
    graph = build_demo_graph(model=model, build_model=build_model)
    graph.build()
    graph.invoke(
        input={},
        attributes={
            "task": args.task,
            "description": args.task,
            "project_name": args.name,
            "name": args.name,
            "org_name": args.org,
            "org": args.org,
            "start_time": time.strftime("%Y%m%d%H%M%S", time.localtime()),
            "gui": "A graphical user interface is required.",
        },
    )


if __name__ == "__main__":
    main()
