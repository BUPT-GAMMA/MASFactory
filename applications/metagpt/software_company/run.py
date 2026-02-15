from __future__ import annotations

import argparse
import os
import re
import time

if __package__ in (None, ""):
    # Allow running as a script from the repo root:
    # `python applications/metagpt/software_company/run.py ...`
    import sys
    from pathlib import Path

    _REPO_ROOT = str(Path(__file__).resolve().parents[3])
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)

from masfactory import OpenAIModel

from applications.metagpt.software_company.software_company import create_software_company_graph


_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _sanitize_project_name(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value)
    value = value.strip("_")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MetaGPT software-company workflow (single task).")
    parser.add_argument(
        "--task",
        type=str,
        required=True,
        help="User requirement / task description.",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="metagpt_project",
        help="Project name used for the output folder.",
    )
    parser.add_argument(
        "--phase",
        type=str,
        default="full",
        choices=["full", "planning", "build"],
        help="Workflow phase to run.",
    )
    parser.add_argument(
        "--enable-qa",
        action="store_true",
        help="Enable optional QA nodes (if supported by the workflow).",
    )
    parser.add_argument("--max-dev-iterations", type=int, default=40, help="Maximum DevLoop iterations.")
    parser.add_argument("--max-retries-per-task", type=int, default=3, help="Maximum retries per DevLoop task.")

    parser.add_argument(
        "--model",
        type=str,
        default=os.getenv("OPENAI_MODEL_NAME") or os.getenv("MODEL_NAME") or "gpt-4o-mini",
        help="OpenAI model name.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY") or "",
        help="OpenAI API key (defaults to OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL") or _DEFAULT_BASE_URL,
        help=f"OpenAI API base URL (default: {_DEFAULT_BASE_URL}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    api_key = (args.api_key or "").strip()
    if not api_key:
        raise SystemExit("Missing OpenAI API key: set OPENAI_API_KEY or pass --api-key.")

    base_url = (args.base_url or "").strip() or _DEFAULT_BASE_URL
    project_name = _sanitize_project_name(str(args.name))
    if not project_name:
        project_name = f"metagpt_{time.strftime('%Y%m%d_%H%M%S')}"

    model = OpenAIModel(
        api_key=api_key,
        base_url=base_url,
        model_name=str(args.model),
    )

    graph = create_software_company_graph(
        model=model,
        project_name=project_name,
        max_dev_iterations=int(args.max_dev_iterations),
        max_retries_per_task=int(args.max_retries_per_task),
        enable_qa=bool(args.enable_qa),
        phase=str(args.phase),
    )

    graph.build()

    print("=" * 80)
    print("MetaGPT Software Company Workflow (MASFactory)")
    print("=" * 80)
    print(f"Project: {project_name}")
    print(f"Phase  : {args.phase}")
    print("=" * 80)

    result, attributes = graph.invoke({"raw_requirement": str(args.task)})

    output_dir = getattr(graph, "_project_path", None)
    if isinstance(output_dir, str) and output_dir:
        print(f"\nOutput directory: {output_dir}")

    if isinstance(result, dict) and "final_answer" in result:
        print("\n" + "=" * 80)
        print("Final Report")
        print("=" * 80)
        print(result.get("final_answer", ""))

    # Also show a compact attribute snapshot for debugging.
    if isinstance(attributes, dict):
        print("\n" + "=" * 80)
        print("Attributes (keys)")
        print("=" * 80)
        print(", ".join(sorted(attributes.keys())))


if __name__ == "__main__":
    main()
