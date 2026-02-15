import os
import sys
import json
from pathlib import Path
from typing import Final

# Ensure repo root is importable when running as a script.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from masfactory import (
    RootGraph, Loop, Agent, CustomNode, LogicSwitch, Edge,
    OpenAIModel, HistoryMemory, JsonMessageFormatter
)
MAX_TURNS: Final[int] = 8

SUSPECT1_PROMPT: Final[str] = """
There are three people (Police, Suspect1, Suspect2) in the scene.

You are now simulating a famous experiment called prisoner's dilemma.

Below is the description of your role. You are Suspect1! You are going to match wits and courage with Suspect2 to come out victorious in this interrogation.
You will have to talk to Police several times and only the final decision will count.
You are a Sophisticated Egoist, you always seek for your personal interests best.
Suspect2 has ever betrayed you.

[IMPORTANT!]
- Your primary goal is trying to make Yourself innocent and reduce your sentence as far as possible in this dilemma.
- When you hear Police saying "Attention!", you are going to make your final decision and Please start with "My final decision is:".

When speaking, please output a response in the following format:
Action: Speak
Action Input: (what you want to say)

What will you, Suspect1, speak at this round? Please give your response based on the above history. Remember to give your response STRICTLY in the above response format.
"""

SUSPECT2_PROMPT: Final[str] = """
There are three people (Police, Suspect1, Suspect2) in the scene.

You are now simulating a famous experiment called prisoner's dilemma.

Below is the description of your role. You are Suspect2! You are going to match wits and courage with Suspect1 to come out victorious in this interrogation.
You will have to talk to Police several times and only the final decision will count.

You have ever betrayed Suspect1 once.

[IMPORTANT!]
- Your primary goal is trying to make Yourself innocent and reduce your sentence as far as possible in this dilemma.
- When you hear Police saying "Attention!", you are going to make your final decision and Please start with "My final decision is:".

When speaking, please output a response in the following format:
Action: Speak
Action Input: (what you want to say)

What will you, Suspect2, speak at this round? Please give your response based on the above history. Remember to give your response STRICTLY in the above response format.
"""

POLICE_PROMPT: Final[str] = """
There are three people (Police, Suspect1, Suspect2) in the scene.

You are now simulating a famous experiment called prisoner's dilemma.

Below is the description of your role. You are now the Police. You have arrested two suspects. However, they both refused to confess to their crime.
Your goal is to try to convict both suspects, therefore you come up with the following rules:
- If one of the suspects is willing to testify against the other and the other one remains silent, then the one who testifies will be released immediately, while the silent one will be sentenced to TEN years in prison.
- If both of the suspects remain silent, they will each receive a sentence of ONE year in prison.
- If both of the suspects choose to testify against each other, they will each receive a sentence of FIVE years in prison.

You are now interrogating both Suspects in turn. When you receive the message from Suspect1 you should transfer the information to Suspect2, vice versa.
Both suspects are not allowed to communicate with each other, and you can adopt various strategies to talk with suspects in order to make them both confess to the crime, including exploiting the uncertainty and the suspicion of each other.

[IMPORTANT!]
- You are requested to briefly describe the above rules to the suspects at the beginning of the conversation.
- You are requested to STATE the final judgement to both suspects when they make their final decision.

When speaking, please output a response in the following format:
Action: Speak
Action Input: (what you want to say)

What will you, Police, speak at this round? Please give your response based on the above history. Remember to give your response STRICTLY in the above response format.
"""
def create_prisoner_dilemma_graph(
    model_name: str = "gpt-4o-mini",
    max_turns: int = MAX_TURNS
) -> RootGraph:
    """Create the prisoner's dilemma simulation graph.

    Args:
        model_name: Model name.
        max_turns: Maximum number of turns.

    Returns:
        RootGraph: A built RootGraph instance.
    """
    
    # Model adapter.
    model = OpenAIModel(
        model_name=model_name,
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL"),
    )
    
    formatter = JsonMessageFormatter()
    
    # Memory.
    memory_suspect1 = HistoryMemory(memory_size=20)
    memory_suspect2 = HistoryMemory(memory_size=20)
    memory_police = HistoryMemory(memory_size=40)
    root = RootGraph(name="prisoner_dilemma")
    
    # Main loop.
    main_loop = root.create_node(
        Loop,
        name="interrogation_loop",
        max_iterations=max_turns,
        attributes={"current_iteration": 0}
    )
    
    root.edge_from_entry(
        receiver=main_loop,
        keys={"last_message": "last message from the previous player"}
    )
    
    root.edge_to_exit(
        sender=main_loop,
        keys={"last_message": "last message from the current player"}
    )
    # Pre-step node.
    before_step = main_loop.create_node(
        CustomNode,
        name="before_step"
    )
    
    # Routing switch.
    switch = main_loop.create_node(
        LogicSwitch,
        name="logic_switch"
    )
    
    # Agents
    suspect1 = main_loop.create_node(
        Agent,
        name="suspect1",
        model=model,
        instructions=SUSPECT1_PROMPT,
        pull_keys={},
        memories=[memory_suspect1]
    )
    
    suspect2 = main_loop.create_node(
        Agent,
        name="suspect2",
        model=model,
        instructions=SUSPECT2_PROMPT,
        pull_keys={},
        memories=[memory_suspect2]
    )
    
    police = main_loop.create_node(
        Agent,
        name="police",
        model=model,
        instructions=POLICE_PROMPT,
        pull_keys={},
        memories=[memory_police]
    )
    
    # Post-step node.
    after_step = main_loop.create_node(
        CustomNode,
        name="after_step"
    )
    main_loop.edge_from_controller(
        receiver=before_step,
        keys={"last_message": "last message from the previous player"}
    )
    
    main_loop.create_edge(
        sender=before_step,
        receiver=switch,
        keys={
            "env_description": "environment description",
            "suspect_id": "suspect 1 or suspect 2",
            "suspect_statement": "the suspect's statement",
            "police_statement": "the police's statement"
        }
    )
    
    # Switch → Agents
    edge_to_suspect1 = main_loop.create_edge(
        sender=switch,
        receiver=suspect1,
        keys={"police_statement": "the police's statement"}
    )
    
    edge_to_suspect2 = main_loop.create_edge(
        sender=switch,
        receiver=suspect2,
        keys={"police_statement": "the police's statement"}
    )
    
    edge_to_police = main_loop.create_edge(
        sender=switch,
        receiver=police,
        keys={
            "suspect_statement": "the suspect's statement",
            "suspect_id": "suspect 1 or suspect 2",
            "env_description": "environment description"
        }
    )
    
    # Agents → After Step
    main_loop.create_edge(
        sender=suspect1,
        receiver=after_step,
        keys={"suspect1_statement": "your statement"}
    )
    
    main_loop.create_edge(
        sender=suspect2,
        receiver=after_step,
        keys={"suspect2_statement": "your statement"}
    )
    
    main_loop.create_edge(
        sender=police,
        receiver=after_step,
        keys={"police_statement": "your statement"}
    )
    
    main_loop.edge_to_controller(
        sender=after_step,
        keys={"last_message": "last message"}
    )

    def police_order_rule(message, attributes) -> bool:
        # Police speaks on even turns.
        current_iteration = attributes.get("current_iteration", 0) - 1
        return current_iteration % 2 == 0
    
    def suspect1_order_rule(message, attributes) -> bool:
        # Suspect1 speaks on turns 1, 5, 9, ...
        current_iteration = attributes.get("current_iteration", 0) - 1
        return current_iteration % 4 == 1
    
    def suspect2_order_rule(message, attributes) -> bool:
        # Suspect2 speaks on turns 3, 7, 11, ...
        current_iteration = attributes.get("current_iteration", 0) - 1
        return current_iteration % 4 == 3
    
    switch.condition_binding(police_order_rule, edge_to_police)
    switch.condition_binding(suspect1_order_rule, edge_to_suspect1)
    switch.condition_binding(suspect2_order_rule, edge_to_suspect2)
    
    # Custom node callbacks.
    
    def before_step_logic(message, attributes):
        # Pre-step: prepare per-turn environment descriptions.
        last_message_json = message if isinstance(message, dict) else json.loads(message) if message else {}
        current_iteration = attributes.get("current_iteration", 0) - 1
        
        print(f"{'='*60}")
        print(f"Round {current_iteration + 1} / {max_turns}")
        print(f"{'='*60}")
        
        result = {
            "env_description": "",
            "suspect_id": "",
            "suspect_statement": "",
            "police_statement": ""
        }
        
        last_msg = last_message_json.get("last_message", "")
        
        if current_iteration == 0:
            result["env_description"] = "You are now talking to Both Suspects."
            result["suspect_id"] = "no suspect statement yet."
            result["suspect_statement"] = last_msg
        elif current_iteration % 2 == 1:
            result["police_statement"] = last_msg
        elif current_iteration % 4 == 0:
            result["env_description"] = "You are now talking to Suspect1."
            result["suspect_id"] = "suspect 1"
            result["suspect_statement"] = last_msg
        elif current_iteration % 4 == 2:
            result["env_description"] = "You are now talking to Suspect2."
            result["suspect_id"] = "suspect 2"
            result["suspect_statement"] = last_msg
        
        return result
    
    def after_step_logic(message, attributes):
        # Post-step: extract the current statement.
        message_json = message if isinstance(message, dict) else json.loads(message) if message else {}
        
        suspect1_stmt = message_json.get("suspect1_statement")
        suspect2_stmt = message_json.get("suspect2_statement")
        police_stmt = message_json.get("police_statement")
        
        statement = suspect1_stmt or suspect2_stmt or police_stmt or ""
        
        if statement:
            # Extract "Action Input:" if present.
            if "Action Input:" in str(statement):
                lines = str(statement).split("\n")
                for line in lines:
                    if "Action Input:" in line:
                        statement = line.split("Action Input:", 1)[-1].strip()
                        break
            print(f"Statement: {statement[:200]}...")
        
        return {"last_message": statement}
    
    before_step.set_forward(before_step_logic)
    after_step.set_forward(after_step_logic)
    
    return root

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Run Prisoner's Dilemma simulation")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="Model name")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS, help="Maximum turns")
    args = parser.parse_args()
    
    print("=" * 80)
    print("🚔 Prisoner's Dilemma simulation")
    print("=" * 80)
    print(f"Model: {args.model}")
    print(f"Max turns: {args.max_turns}")
    print()
    
    graph = create_prisoner_dilemma_graph(
        model_name=args.model,
        max_turns=args.max_turns
    )
    
    graph.build()
    output, attributes = graph.invoke({"last_message": ""})
    
    print()
    print("=" * 80)
    print("🏁 Simulation completed")
    print("=" * 80)
    print(f"Final message: {output.get('last_message', '')[:500]}")


if __name__ == "__main__":
    main()
