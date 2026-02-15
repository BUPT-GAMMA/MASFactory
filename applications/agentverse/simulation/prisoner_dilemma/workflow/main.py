"""Prisoner's dilemma simulation workflow."""

import os
import sys
from pathlib import Path

# Ensure repo root is importable when running as a script.
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from masfactory import RootGraph, Loop, Agent, CustomNode, Model, HistoryMemory


def create_prisoner_dilemma_graph(model: Model, max_turns: int = 8) -> RootGraph:
    """
    Create the prisoner's dilemma simulation graph.

    Args:
        model: The language model to use.
        max_turns: Maximum number of conversation turns.

    Returns:
        RootGraph: The complete workflow graph.
    """
    
    graph = RootGraph(name="prisoner_dilemma")
    agent_configs = [
        {
            "name": "Police",
            "role_description": """You are now the Police. You have arrested two suspects. However, they both refused to confess to their crime.
Your goal is try to convict both suspects, therefore you come up with the following rules.
- If one of the suspect are willing to testifies against the other and the other one remains silent, then the one who testifies will be released immediately, while the silent one will be sentenced to TEN years in prison.
- If both of the suspects remain silent, they will each receive a sentence of ONE year in prison.
- If both of the suspects choose to testify against each other, they will each receive a sentence of FIVE years in prison.
You are now interrogating with both Suspects in turn, when you receive the message from Suspect1 you should transfer the information to Suspect2, vice versa.
Both suspects are not allowed to communicate with each other, and you can adopt various strategy to talk with suspects in order to make them both confess to the crime, including exploiting the uncertainess and the suspicion of each other.
[IMPORTANT!]
- You are request to briefly describe the above rules to the suspects at the beginning of the conversation.
- You are request to STATE the final judgement to both suspects when they make their final decision.""",
        },
        {
            "name": "Suspect1",
            "role_description": """You are Suspect1 !!! You are going to match wits and courage with Suspect2 to come out victorious in this interrogation.
You will have to talk to Police several times and only the final decision will count.
You are a Sophisticated Egoist, you always seek for your personal interests best.
Suspect2 has ever betrayed on you.
[IMPORTANT!]
- Your primary goal is trying to make Yourself innocent and reduce your sentence as far as possible in this dilemma.
- When you hear Police saying "Attention!", you are going to made your final decision and Please start with "My final decision is:".""",
        },
        {
            "name": "Suspect2",
            "role_description": """You are Suspect2 !!! You are going to match wits and courage with Suspect1 to come out victorious in this interrogation.
You will have to talk to Police several times and only the final decision will count.
You have ever betray Suspect1 once.
[IMPORTANT!]
- Your primary goal is trying to make Yourself innocent and reduce your sentence as far as possible in this dilemma.
- When you hear Police saying "Attention!", you are going to made your final decision and Please start with "My final decision is:".""",
        },
    ]
    shared_memory = HistoryMemory()

    def check_max_turns(messages: dict, attributes: dict) -> bool:
        current_turn = attributes.get("current_turn", 0)
        return current_turn >= max_turns

    conversation_loop = graph.create_node(
        Loop,
        name="conversation_loop",
        max_iterations=max_turns,
        terminate_condition_function=check_max_turns,
        pull_keys={},
        push_keys={
            "conversation_history": "The complete conversation history",
            "current_turn": "Current turn number",
            "chat_history": "Formatted chat history"
        },
        attributes={
            "current_turn": 0,
            "conversation_history": [],
            "chat_history": "",
            "next_agent_idx": 0
        }
    )
    conversation_agent = conversation_loop.create_node(
        Agent,
        name="conversation_agent",
        role_name="Participant",
        instructions="""There are three people (Police, Suspect1, Suspect2) in the scene.

You are now simulating a famous experiment called prisoner's dilemma.

Below is the description of your role: {role_description}

Your current role: {current_role}

When speaking, please output a response in the following format with two fields Action and Action Input:
Action: Speak
Action Input: (You should put what you want to speak here)

Here is the conversation history:
{chat_history}

What will you, {current_role}, speak at this round? Please give your response based on the above history. Remember to give your response STRICTLY in the above response format. Do not add any additional field or line break to your response!""",
        model=model,
        memories=[shared_memory],
        pull_keys=None,  # Pull all attributes from the loop.
        push_keys={},
    )
    
    def process_message(messages: dict, attributes: dict) -> dict:
        current_turn = attributes.get("current_turn", 0)
        conversation_history = attributes.get("conversation_history", [])
        next_agent_idx = attributes.get("next_agent_idx", 0)

        message = messages.get("message", "")

        # Extract "Action Input:" if present.
        actual_message = message
        if "Action Input:" in message:
            lines = message.split("\n")
            for line in lines:
                if line.strip().startswith("Action Input:"):
                    actual_message = line.split("Action Input:", 1)[1].strip()
                    break

        speaker_name = agent_configs[next_agent_idx]["name"]

        conversation_history.append({
            "speaker": speaker_name,
            "message": actual_message
        })
        
        current_turn += 1

        next_agent_idx = current_turn % len(agent_configs)

        chat_history = "\n".join([
            f"{entry['speaker']}: {entry['message']}"
            for entry in conversation_history
        ])

        return {
            "conversation_history": conversation_history,
            "chat_history": chat_history,
            "current_turn": current_turn,
            "next_agent_idx": next_agent_idx,
            "message": actual_message
        }
    
    message_processor = conversation_loop.create_node(
        CustomNode,
        name="message_processor",
        forward=process_message,
        pull_keys=None,
        push_keys=None,
    )

    def select_role(messages: dict, attributes: dict) -> dict:
        next_agent_idx = attributes.get("next_agent_idx", 0)
        next_agent = agent_configs[next_agent_idx]

        chat_history = attributes.get("chat_history", "")

        return {
            "chat_history": chat_history,
            "current_role": next_agent["name"],
            "role_description": next_agent["role_description"],
            "chat_history": attributes.get("chat_history", "")
        }

    role_selector = conversation_loop.create_node(
        CustomNode,
        name="role_selector",
        forward=select_role,
        pull_keys=None,
        push_keys=None
    )
    
    conversation_loop.edge_from_controller(
        receiver=role_selector,
        keys={}
    )

    conversation_loop.create_edge(
        sender=role_selector,
        receiver=conversation_agent,
        keys={
            "chat_history": "The conversation history",
            "current_role": "The current role name",
            "role_description": "The role description"
        }
    )

    conversation_loop.create_edge(
        sender=conversation_agent,
        receiver=message_processor,
        keys={"message": "The agent's response"}
    )

    conversation_loop.edge_to_controller(
        sender=message_processor,
        keys={
            "conversation_history": "The complete conversation history",
            "chat_history": "Formatted chat history",
            "current_turn": "Current turn number",
            "next_agent_idx": "Index of next agent to speak",
            "message": "Last message"
        }
    )
    graph.edge_from_entry(
        receiver=conversation_loop,
        keys={}
    )
    graph.edge_to_exit(
        sender=conversation_loop,
        keys={
            "conversation_history": "conversation_history"
        }
    )
    graph.build()
    
    return graph
