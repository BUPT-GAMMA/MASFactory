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
from applications.agentverse.simulation.prisoner_dilemma.workflow.main import create_prisoner_dilemma_graph


def main():
    parser = argparse.ArgumentParser(description="Prisoner's Dilemma simulation")
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-mini",
        help="Model name to use (default: gpt-4o-mini)"
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=8,
        help="Maximum conversation turns (default: 8)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(_REPO_ROOT / "applications" / "agentverse" / "assets" / "output" / "prisoner_dilemma"),
        help="Output directory for results",
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("⚖️  Prisoner's Dilemma simulation")
    print("=" * 80)
    print()
    print("📋 Configuration:")
    print(f"  - Model: {args.model}")
    print(f"  - Max turns: {args.max_turns}")
    print()
    
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")
    
    if not api_key:
        print("❌ Error: OPENAI_API_KEY environment variable not set")
        print("   Set it in your shell, or create `.env.sh` and `source .env.sh`")
        return 1
    
    print("🔧 Initializing model...")
    model = OpenAIModel(
        model_name=args.model,
        api_key=api_key,
        base_url=base_url
    )
    
    print("🔧 Building simulation graph...")
    graph = create_prisoner_dilemma_graph(
        model=model,
        max_turns=args.max_turns
    )
    graph.build()
    
    print()
    print("=" * 80)
    print("👥 Participants:")
    print("=" * 80)
    print("1. Police - interrogator trying to obtain confessions")
    print("2. Suspect 1 - shrewd egoist (previously betrayed by suspect 2)")
    print("3. Suspect 2 - has betrayed suspect 1 once")
    print("=" * 80)
    print()
    
    print("⚙️  Starting simulation...")
    print("-" * 80)
    print()
    
    result, _attrs = graph.invoke({})
    
    conversation_history = result.get("conversation_history", [])
    
    print()
    print("=" * 80)
    print("📊 Simulation results:")
    print("=" * 80)
    print()
    print("💬 Conversation:")
    print()
    
    for i, entry in enumerate(conversation_history, 1):
        speaker = entry.get("speaker", "Unknown")
        message = entry.get("message", "")
        print(f"Turn {i} - {speaker}:")
        print(f"  {message}")
        print()
    
    print(f"Total turns: {len(conversation_history)}")
    print()
    
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"result_{timestamp}.json")
    
    output_data = {
        "model": args.model,
        "max_turns": args.max_turns,
        "actual_turns": len(conversation_history),
        "conversation_history": conversation_history
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Results saved to: {output_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
