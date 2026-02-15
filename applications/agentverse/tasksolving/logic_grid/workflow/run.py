"""
Logic Grid Task Runner

This script runs the logic grid puzzle solving task.
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
repo_root = _find_repo_root(Path(__file__).resolve())
sys.path.insert(0, str(repo_root))

from masfactory.adapters.model import OpenAIModel
from main import create_logic_grid_graph


def main():
    parser = argparse.ArgumentParser(description="Run Logic Grid task")
    parser.add_argument(
        "--task",
        type=str,
        required=True,
        help="The logic problem to solve"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-mini",
        help="Model to use (default: gpt-4o-mini)"
    )
    parser.add_argument(
        "--max-turn",
        type=int,
        default=3,
        help="Maximum number of outer loop turns (default: 3)"
    )
    parser.add_argument(
        "--num-critics",
        type=int,
        default=2,
        help="Number of critic agents (default: 2)"
    )
    parser.add_argument(
        "--max-inner-turns",
        type=int,
        default=3,
        help="Maximum number of inner discussion rounds (default: 3)"
    )
    
    args = parser.parse_args()
    
    # Print header
    print("=" * 80)
    print("🧩 Logic Grid Task")
    print("=" * 80)
    print()
    print("📋 Configuration:")
    print(f"  - Model: {args.model}")
    print(f"  - Max turns: {args.max_turn}")
    print(f"  - Num critics: {args.num_critics}")
    print(f"  - Max inner turns: {args.max_inner_turns}")
    print()
    print("📝 Problem:")
    print(f"  {args.task}")
    print()
    
    # Get API key and base URL from environment
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")
    
    if not api_key:
        print("❌ Error: OPENAI_API_KEY environment variable not set")
        print("Set it in your shell, or create `.env.sh` and `source .env.sh`:")
        print("  export OPENAI_API_KEY='your-api-key'")
        sys.exit(1)
    
    # Initialize model
    print("🔧 Initializing model...")
    model = OpenAIModel(
        model_name=args.model,
        api_key=api_key,
        base_url=base_url
    )
    
    # Create graph
    print("🔧 Building task graph...")
    graph = create_logic_grid_graph(
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
    
    # Run the task
    print()
    print("⚙️  Starting task solving...")
    print("-" * 80)
    print()
    
    result, _attrs = graph.invoke(input_data)
    
    # Extract solution
    solution = result.get("solution", "No solution generated")
    evaluation = result.get("evaluation", "No evaluation")
    success = result.get("success", False)
    
    # Print results
    print()
    print("=" * 80)
    print("📊 Results:")
    print("=" * 80)
    print()
    print("💡 Solution:")
    print(solution)
    print()
    
    # Save results to file
    output_dir = Path(__file__).parent.parent / "assets" / "output"
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
        "evaluation": evaluation,
        "success": success,
        "timestamp": timestamp
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Results saved to: {output_file.relative_to(Path.cwd())}")
    print()


if __name__ == "__main__":
    main()
