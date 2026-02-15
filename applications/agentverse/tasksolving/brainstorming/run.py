"""Run the brainstorming task workflow."""

import os
import sys
import argparse
import json
from datetime import datetime
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError(f"Cannot locate repo root from: {start}")


# Add repo root to sys.path to avoid fragile fixed-depth assumptions.
repo_root = _find_repo_root(Path(__file__).resolve())
sys.path.insert(0, str(repo_root))

from workflow.main import create_brainstorming_graph
from masfactory.adapters.model import OpenAIModel


def main():
    parser = argparse.ArgumentParser(description="Run brainstorming task")
    parser.add_argument("--task", type=str, required=True, help="Task description")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="Model name")
    parser.add_argument("--max-turn", type=int, default=3, help="Maximum number of outer loop iterations")
    parser.add_argument("--max-inner-turns", type=int, default=0, help="Maximum number of inner loop iterations")
    parser.add_argument("--num-critics", type=int, default=4, help="Number of critic agents")
    parser.add_argument("--base-url", type=str, default=None, help="Base URL for OpenAI API")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(repo_root / "applications" / "agentverse" / "assets" / "output" / "brainstorming"),
        help="Output directory for results",
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("🚀 Brainstorming Task")
    print("=" * 80)
    print()
    print("📋 Configuration:")
    print(f"  - Model: {args.model}")
    print(f"  - Max turns: {args.max_turn}")
    print(f"  - Max inner turns: {args.max_inner_turns}")
    print(f"  - Number of critics: {args.num_critics}")
    print()
    
    model_kwargs = {}
    
    base_url = args.base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL")
    if base_url:
        model_kwargs["base_url"] = base_url
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")
    
    model = OpenAIModel(
        model_name=args.model,
        api_key=api_key,
        **model_kwargs
    )
    
    print("🔨 Building graph...")
    graph = create_brainstorming_graph(
        task_description=args.task,
        model=model,
        max_turn=args.max_turn,
        max_inner_turns=args.max_inner_turns,
        num_critics=args.num_critics
    )
    graph.build()
    print("✅ Graph built successfully")
    print()
    
    print("🚀 Running task...")
    print(f"📝 Task: {args.task}")
    print("-" * 80)
    result, _attrs = graph.invoke({
        "task_description": args.task
    })
    print("-" * 80)
    print()
    
    print("📊 Results:")
    print(f"  - Success: {result.get('success', False)}")
    
    if "solution" in result:
        print(f"\n💡 Solution:\n{result['solution']}")
    
    if "message" in result:
        print(f"\n💬 Evaluation:\n{result['message']}")
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"brainstorming_{timestamp}.json"
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "task": args.task,
            "model": args.model,
            "max_turn": args.max_turn,
            "max_inner_turns": args.max_inner_turns,
            "num_critics": args.num_critics,
            "timestamp": timestamp,
            "result": result
        }, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Results saved to: {output_file}")
    print("\n✨ Task completed!")


if __name__ == "__main__":
    main()
