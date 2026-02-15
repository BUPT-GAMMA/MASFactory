"""Run the NLP classroom 3-player simulation."""

import os
import sys
import argparse
import json
from datetime import datetime
from pathlib import Path

# Ensure repo root is importable when running as a script.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from masfactory.adapters.model import OpenAIModel
from applications.agentverse.simulation.nlp_classroom_3players.workflow.main import create_nlp_classroom_graph


def main():
    parser = argparse.ArgumentParser(description="NLP Classroom 3 Players Simulation")
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-mini",
        help="Model name to use (default: gpt-4o-mini)"
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=10,
        help="Maximum number of conversation turns (default: 10)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(_REPO_ROOT / "applications" / "agentverse" / "assets" / "output" / "nlp_classroom_3players"),
        help="Output directory for results",
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("🎓 NLP Classroom (3 players) Simulation")
    print("=" * 80)
    print()
    print("📋 Configuration:")
    print(f"  - Model: {args.model}")
    print(f"  - Max turns: {args.max_turns}")
    print(f"  - Output dir: {args.output_dir}")
    print()
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ Error: OPENAI_API_KEY environment variable not set")
        print("   Run: export OPENAI_API_KEY='your-api-key'")
        sys.exit(1)
    
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL")
    model_kwargs = {"api_key": api_key}
    if base_url:
        model_kwargs["base_url"] = base_url
    
    print("🔧 Initializing model...")
    model = OpenAIModel(
        model_name=args.model,
        **model_kwargs
    )
    print("✅ Model initialized")
    print()
    
    print("🔨 Building simulation graph...")
    graph = create_nlp_classroom_graph(
        model=model,
        max_turns=args.max_turns
    )
    graph.build()
    print("✅ Graph built successfully")
    print()
    
    print("🚀 Starting simulation...")
    print("-" * 80)
    result, _attrs = graph.invoke({})
    print("-" * 80)
    print()
    
    print("📊 Simulation results:")
    
    if "conversation_history" in result:
        history = result["conversation_history"]
        print(f"  - Total turns: {len(history)}")
        print()
        print("💬 Conversation history:")
        for i, entry in enumerate(history, 1):
            speaker = entry.get("speaker", "Unknown")
            message = entry.get("message", "")
            print(f"\n{i}. {speaker}:")
            print(f"   {message}")
    
    print()
    
    os.makedirs(args.output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(args.output_dir, f"nlp_classroom_3players_{timestamp}.json")
    
    output_data = {
        "model": args.model,
        "max_turns": args.max_turns,
        "timestamp": timestamp,
        "result": result
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Results saved to: {output_file}")
    print("\n✨ Simulation completed!")


if __name__ == "__main__":
    main()
