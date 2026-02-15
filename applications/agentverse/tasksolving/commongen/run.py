"""
CommonGen Task Runner - MASFactory Implementation

This script runs the CommonGen task using the MASFactory framework.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError(f"Cannot locate repo root from: {start}")


# Add repo root to path (stable across directory layout changes).
current_dir = Path(__file__).resolve().parent
repo_root = _find_repo_root(Path(__file__).resolve())
sys.path.insert(0, str(repo_root))

from masfactory.adapters.model import OpenAIModel
from workflow.main import create_commongen_graph


def main():
    parser = argparse.ArgumentParser(description="Run CommonGen task")
    parser.add_argument(
        "--task",
        type=str,
        default="dog, park, run, happy",
        help="Comma-separated words to include in the generated text"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-mini",
        help="Model name to use"
    )
    parser.add_argument(
        "--max-turn",
        type=int,
        default=3,
        help="Maximum number of turns"
    )
    parser.add_argument(
        "--num-critics",
        type=int,
        default=2,
        help="Number of critic agents"
    )
    parser.add_argument(
        "--max-inner-turns",
        type=int,
        default=3,
        help="Maximum number of inner decision-making turns"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(repo_root / "applications" / "agentverse" / "assets" / "output" / "commongen"),
        help="Output directory for results",
    )
    
    args = parser.parse_args()
    
    # Get API key and base URL from environment
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")

    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")

    # Create model
    model = OpenAIModel(
        model_name=args.model,
        api_key=api_key,
        base_url=base_url
    )
    
    # Create graph
    print(f"Creating CommonGen graph for task: {args.task}")
    print(f"Model: {args.model}")
    print(f"Max turns: {args.max_turn}")
    print(f"Num critics: {args.num_critics}")
    print(f"Max inner turns: {args.max_inner_turns}")
    print()
    
    graph = create_commongen_graph(
        task=args.task,
        model=model,
        max_turn=args.max_turn,
        num_critics=args.num_critics,
        max_inner_turns=args.max_inner_turns
    )
    
    # Prepare input
    input_data = {
        "task_description": args.task,
        "advice": "",
        "previous_plan": ""
    }
    
    # Run the graph
    print("Running graph...")
    print("=" * 80)
    result, _attrs = graph.invoke(input_data)
    print("=" * 80)
    print()
    
    # Extract results
    solution = result.get("solution", "")
    execution_result = result.get("result", "")
    evaluation = result.get("message", "")
    success = result.get("success", False)
    
    print("Results:")
    print("-" * 80)
    print(f"Task: {args.task}")
    print()
    print("Generated solution:")
    print(solution)
    print()
    print("Execution result:")
    print(execution_result)
    print()
    print("Evaluation:")
    print(evaluation)
    print()
    print(f"Success: {success}")
    print("-" * 80)
    
    # Save results
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"result_{timestamp}.json"
    
    output_data = {
        "task": args.task,
        "model": args.model,
        "max_turn": args.max_turn,
        "num_critics": args.num_critics,
        "max_inner_turns": args.max_inner_turns,
        "solution": solution,
        "execution_result": execution_result,
        "evaluation": evaluation,
        "success": success,
        "timestamp": timestamp
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print()
    print(f"Results saved to: {output_file}")


if __name__ == "__main__":
    main()
