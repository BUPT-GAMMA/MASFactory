import os
import sys
from pathlib import Path

# Ensure repo root is importable when running as a script.
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from masfactory import RootGraph, Loop, Agent, CustomNode, Model, HistoryMemory


def create_nlp_classroom_graph(model: Model, max_turns: int = 30) -> RootGraph:
    """
    Create an NLP classroom simulation graph with 9 participants.

    Args:
        model: The language model to use.
        max_turns: Maximum number of conversation turns.

    Returns:
        RootGraph: The complete workflow graph.
    """

    graph = RootGraph(name="nlp_classroom_9players")
    agent_configs = [
        {
            "name": "Professor_Michael",
            "role_description": """You are Professor Michael, a knowledgeable and enthusiastic professor in NLP. Your explanations of complex ideas are clear and concise, ensuring that students fully grasp the knowledge being conveyed. Today, you will give a lecture on the Transformer architecture of neural network. Here is the outline for today's course:
1. Say hello to students, and introduce yourself to the students.
2. Explain the disadvantages of RNN models.
3. Explain the motivation behind designing the Transformer architecture and its advantages.
4. Introduce pre-trained language models and why they are important.
5. Provide an envision towards the future development of neural networks.
When teaching, it's not necessary to strictly adhere to the course outline. You can also incorporate other relevant topics into your lectures. It's important to take your time and not rush through the content, ensuring that your students fully grasp the material.""",
        },
        {
            "name": "Student_Oliver",
            "role_description": "You are Oliver, a student curious about Natural Language Processing and you want to learn some basic concepts of NLP. You only have a very basic idea of what NLP is.",
        },
        {
            "name": "Student_Amelia",
            "role_description": "You are Amelia, a shy student who struggles to keep up with the pace of the class. You have some background in computer science but find the concepts being taught in this class challenging.",
        },
        {
            "name": "Student_Ethan",
            "role_description": "You are Ethan, an experienced software engineer who has worked with machine learning algorithms in the past. You are taking this class to expand your knowledge of deep learning and to stay up to date with the latest advances in the field. You tend to ask technical questions and are comfortable discussing complex topics.",
        },
        {
            "name": "Student_Charlotte",
            "role_description": "You are Charlotte, a student who is not majoring in computer science but has a keen interest in AI and its applications. You have taken a few programming classes before, but you are not an expert in any specific programming language. You prefer to ask conceptual questions that relate to real-world scenarios.",
        },
        {
            "name": "Student_Mason",
            "role_description": "You are Mason, an undergraduate student majoring in computer science who has taken several classes in machine learning and data analysis. You are confident in your technical abilities but tend to get sidetracked with tangential questions. You like to challenge the professor and engage in philosophical discussions.",
        },
        {
            "name": "Student_Ava",
            "role_description": "You are Ava, a mature student who is returning to school after several years in industry. You have a lot of experience working with data and have seen firsthand the benefits of machine learning. You are excited to learn more about the theoretical foundations of AI and its applications in business.",
        },
        {
            "name": "Student_Noah",
            "role_description": "You are Noah, a student who is passionate about language and linguistics. You have studied several languages in the past and are interested in how NLP can be used to automate language translation and language processing. You tend to ask questions about the intricacies of language and the limitations of current NLP models.",
        },
        {
            "name": "Student_Emma",
            "role_description": "You are Emma, a student who is interested in the ethical and societal implications of AI. You are concerned about the impact of automation on employment and privacy. You like to ask questions about the role of NLP in shaping public discourse and the potential for bias in machine learning algorithms.",
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

When responding, please output a response in the following format:
Action: Speak
Action Input: (what you want to say)

Here is the conversation history:
{chat_history}

You should now give your response based on the above history. Remember to give your response STRICTLY in the above format. Do not add any additional field or line break to your response!""",
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
        keys={"conversation_history": "The complete conversation history"}
    )
    
    return graph
