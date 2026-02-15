"""NLP classroom simulation workflow (3 participants)."""

import os
import sys
from pathlib import Path

# Ensure repo root is importable when running as a script.
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from masfactory import RootGraph, Loop, Agent, CustomNode, Model, HistoryMemory


def create_nlp_classroom_graph(model: Model, max_turns: int = 10) -> RootGraph:
    """Build the classroom simulation graph.

    Args:
        model: LLM model instance.
        max_turns: Maximum number of conversation turns.
    """
    
    graph = RootGraph(name="nlp_classroom_3players")
    agent_configs = [
        {
            "name": "Professor_Micheal",
            "role_description": "You are Prof. Micheal, a knowledgeable professor in NLP. Your answer will be concise and accurate. The answers should be less than 100 words.",
        },
        {
            "name": "Student_Beta",
            "role_description": "You are Beta, a student curious about Natural Language Processing and you want to learn some basic concepts of NLP. You know nothing about the area so you will ask lots of questions.",
        },
        {
            "name": "Teaching_Assistant_Gamma",
            "role_description": "You are Gamma, a teaching assistant of the Natural Language Processing module. You mostly help with logistics and marking, but occasionally handle questions. Your answer should be less than 100 words.",
        }
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
        push_keys={"conversation_history": "The complete conversation history"},
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
        role_name="Classroom Participant",
        instructions="""You are participating in a university classroom discussion about Natural Language Processing.

Your current role: {current_role}
Role description: {role_description}

Here is the conversation history:
{chat_history}

You should now give your response based on the above history.""",
        model=model,
        memories=[shared_memory],
        pull_keys=None,  # Pull all attributes from loop
        push_keys={"message": "Your response message"}  # Output message key
    )
    
    def process_message(messages: dict, attributes: dict) -> dict:
        current_turn = attributes.get("current_turn", 0)
        conversation_history = attributes.get("conversation_history", [])
        next_agent_idx = attributes.get("next_agent_idx", 0)
        
        message = messages.get("message", "")
        
        # Extract "Action Input:" if the agent follows the action format.
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
        pull_keys=None,  # Pull all attributes
        push_keys=None  # Push all outputs back to loop
    )

    def select_role(messages: dict, attributes: dict) -> dict:
        next_agent_idx = attributes.get("next_agent_idx", 0)
        chat_history = attributes.get("chat_history", "")

        current_role = agent_configs[next_agent_idx]["name"]
        role_description = agent_configs[next_agent_idx]["role_description"]

        return {
            "chat_history": chat_history,
            "current_role": current_role,
            "role_description": role_description,
            "next_agent_idx": next_agent_idx
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

    # Role Selector → Conversation Agent
    conversation_loop.create_edge(
        sender=role_selector,
        receiver=conversation_agent,
        keys={
            "chat_history": "The conversation history",
            "current_role": "The current role name",
            "role_description": "The role description"
        }
    )

    # Conversation Agent → Message Processor
    conversation_loop.create_edge(
        sender=conversation_agent,
        receiver=message_processor,
        keys={"message": "The agent's response"}
    )
    
    # Message Processor → Controller (feedback loop)
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
        keys={"conversation_history": "The complete conversation history"}
    )
    
    return graph
