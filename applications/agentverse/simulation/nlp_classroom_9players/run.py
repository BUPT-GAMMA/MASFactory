"""Run the NLP classroom 9-player simulation."""

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
from applications.agentverse.simulation.nlp_classroom_9players.workflow.main import create_nlp_classroom_graph


def main():
    parser = argparse.ArgumentParser(description="NLP Classroom 9 Players Simulation")
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-mini",
        help="Model name to use (default: gpt-4o-mini)"
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=30,
        help="Maximum number of conversation turns (default: 30)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(_REPO_ROOT / "applications" / "agentverse" / "assets" / "output" / "nlp_classroom_9players"),
        help="Output directory for results",
    )

    args = parser.parse_args()

    # Print header
    print("=" * 80)
    print("🎓 NLP Classroom (9 players) Simulation")
    print("=" * 80)
    print()
    print("📋 Configuration:")
    print(f"  - Model: {args.model}")
    print(f"  - Max turns: {args.max_turns}")
    print()
    
    # Create model
    print("🔧 Initializing model...")
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")

    if not api_key:
        print("❌ Error: OPENAI_API_KEY environment variable not set")
        return

    # Clean up base_url (remove trailing colons or slashes)
    if base_url:
        base_url = base_url.rstrip(":/")

    model = OpenAIModel(
        model_name=args.model,
        api_key=api_key,
        base_url=base_url
    )
    
    # Create graph
    print("🔧 Building simulation graph...")
    graph = create_nlp_classroom_graph(
        model=model,
        max_turns=args.max_turns
    )
    
    # Build graph
    graph.build()
    print()
    
    # Print simulation info
    print("=" * 80)
    print("👥 Participants:")
    print("=" * 80)
    print("1. Professor Michael (Professor)")
    print("2. Student Oliver (Student)")
    print("3. Student Amelia (Student)")
    print("4. Student Ethan (Student)")
    print("5. Student Charlotte (Student)")
    print("6. Student Mason (Student)")
    print("7. Student Ava (Student)")
    print("8. Student Noah (Student)")
    print("9. Student Emma (Student)")
    print("=" * 80)
    print()
    
    # Run simulation
    print("⚙️  Starting simulation...")
    print("-" * 80)
    print()
    
    result, _attrs = graph.invoke({})
    
    # Extract results
    conversation_history = result.get("conversation_history", [])
    
    print()
    print("=" * 80)
    print("📊 Simulation results:")
    print("=" * 80)
    print()
    
    # Print conversation
    print("💬 Conversation:")
    print()
    for i, entry in enumerate(conversation_history):
        speaker = entry.get("speaker", "Unknown")
        message = entry.get("message", "")
        print(f"Turn {i+1} - {speaker}:")
        print(f"  {message}")
        print()
    
    print(f"Total turns: {len(conversation_history)}")
    print()
    
    # Save results
    os.makedirs(args.output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(args.output_dir, f"result_{timestamp}.json")
    
    output_data = {
        "model": args.model,
        "max_turns": args.max_turns,
        "actual_turns": len(conversation_history),
        "conversation_history": conversation_history,
        "timestamp": timestamp
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Results saved to: {output_file}")
    print()


if __name__ == "__main__":
    main()
