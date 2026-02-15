"""Runner script for MGSM (Multilingual Grade School Math) task."""

import argparse
import os
import sys
import json
from datetime import datetime
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError(f"Cannot locate repo root from: {start}")


# Add the repository root to the path (stable across directory layout changes).
repo_root = _find_repo_root(Path(__file__).resolve())
sys.path.insert(0, str(repo_root))

from masfactory.adapters.model import OpenAIModel
from workflow.main import create_mgsm_graph


def main():
    parser = argparse.ArgumentParser(description="Run MGSM task")
    parser.add_argument(
        "--task",
        type=str,
        required=True,
        help="The math problem to solve"
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
        help="Maximum number of outer loop iterations"
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
        help="Maximum number of inner loop iterations"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(repo_root / "applications" / "agentverse" / "assets" / "output" / "mgsm"),
        help="Output directory for results",
    )
    
    args = parser.parse_args()
    
    # Get API configuration from environment
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL")
    
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    
    # Clean up base_url
    if base_url:
        base_url = base_url.rstrip(":/")
    
    print("=" * 80)
    print("🧮 MGSM (Multilingual Grade School Math) Task")
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
    
    # Initialize model
    print("🔧 Initializing model...")
    model = OpenAIModel(
        model_name=args.model,
        api_key=api_key,
        base_url=base_url
    )
    
    # Create graph
    print("🔧 Building task graph...")
    graph = create_mgsm_graph(
        model=model,
        task=args.task,
        max_turn=args.max_turn,
        num_critics=args.num_critics,
        max_inner_turns=args.max_inner_turns
    )
    
    print()
    print("⚙️  Starting task solving...")
    print("-" * 80)
    print()

    # Prepare input data
    input_data = {
        "task_description": args.task,
        "advice": "No advice yet.",
        "previous_plan": "No solution yet."
    }

    # Run the graph
    result, _attrs = graph.invoke(input_data)
    
    print()
    print("=" * 80)
    print("📊 Results:")
    print("=" * 80)
    print()
    
    # Extract solution
    solution = result.get("solution", "No solution found")
    evaluation = result.get("evaluation", {})
    
    print("💡 Solution:")
    print(solution)
    print()
    
    if evaluation:
        print("📈 Evaluation:")
        if isinstance(evaluation, dict):
            for key, value in evaluation.items():
                print(f"  {key}: {value}")
        else:
            print(f"  {evaluation}")
        print()
    
    # Save results
    os.makedirs(args.output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(args.output_dir, f"result_{timestamp}.json")
    
    output_data = {
        "task": args.task,
        "model": args.model,
        "max_turn": args.max_turn,
        "num_critics": args.num_critics,
        "max_inner_turns": args.max_inner_turns,
        "solution": solution,
        "evaluation": evaluation,
        "timestamp": timestamp
    }
    
    with open(output_file, "w") as f:
        json.dump(output_data, f, indent=2)
    
    print(f"✅ Results saved to: {output_file}")


if __name__ == "__main__":
    main()
