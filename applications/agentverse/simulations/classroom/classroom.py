import os
import sys
import json
import random
from pathlib import Path
from typing import Final, Dict, List, Callable
from string import Template

# Ensure repo root is importable when running as a script.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from masfactory import (
    RootGraph, Loop, Agent, CustomNode, LogicSwitch, Edge,
    OpenAIModel, HistoryMemory, JsonMessageFormatter, Memory
)
MAX_TURNS: Final[int] = 8

PROFESSOR_PROMPT: Final[str] = """
You are in a university classroom and it is a lecture on the Transformer architecture of neural networks. 
You are Professor Michael, a knowledgeable and enthusiastic professor in NLP. Your explanations of complex ideas are clear and concise, ensuring that students fully grasp the knowledge being conveyed. Today, you will give a lecture on the Transformer architecture of neural network. Here is the outline for today's course:
1. Welcome the students, and introduce yourself to the students.
2. Clearly explain the disadvantages of RNN models.
3. Let the students discuss the additional drawbacks of RNNs in groups.
4. Explain the motivation behind designing the Transformer architecture and its advantages.
5. Introduce pre-trained language models and why they are important.
6. Provide an envision towards the future development of neural networks.

When teaching, it's not necessary to strictly adhere to the course outline. You can also incorporate other relevant topics into your lectures. It's important to take your time and not rush through the content, explaining each topic carefully and ensuring that your students fully grasp the material.

# Rules and Format Instructions for Response

- When you are speaking, you must use the following format:
Action: Speak
Action Input: (what you want to say)

- When several students raise their hands, you can choose to call on ONE of them using the following format:
Action: CallOn
Action Input: (one student's name)

- Once you have called on a student and they have asked their question, it is your responsibility to provide an answer. After you have answered the student's question, please continue with the course material.

- If you want to launch a group discussion, use the following format:
Action: GroupDiscuss
Action Input: Now, you can begin group discussion on (the discussion topic).

After the group discussion, you should ask who would like to share their thoughts.

- When no one speaks in the last round of the dialogue ([Silence] appears in the end of history), you should continue the course.

- You should not answer the questions that have been already answered.

- You must follow the following format with two fields "Action" and "Action Input" for your response in ANY case:
Action: (an action name, it can be one of [Speak, CallOn, Listen, GroupDiscuss])
Action Input: (argument for the action)

Remember to pay attention to the response format instructions, and strictly follow the rules specified above!
"""

STUDENT_PROMPT_TEMPLATE: Final[str] = """
You are in a university classroom and it is a lecture on the Transformer architecture of neural networks. 
${role_description}

# Rules and Format Instructions for Response

- During class, it's recommended that you listen to the professor by responding:
Action: Listen
Action Input: listen

- If you have a question that you think it's worth discussing in class, you should first raise your hand using the following format to let the professor notice you:
Action: RaiseHand
Action Input: raise hand

If the professor does call on your name, you MUST speak or ask a question, and use the following format:
Action: Speak
Action Input: (what you want to ask or speak)

If you raised your hand but are not called on, you should keep listening, or raise your hand again and wait for the professor to call on you. You are NOT allowed to speak if the professor does not call on you. Respect the discipline of the class!

- [IMPORTANT!] You are allowed to speak for one turn right after the professor calls on you. You are also allowed to speak when having a group discussion. You MUST NOT speak in any other cases!

- During group discussion, it is important that you actively participate by sharing your thoughts and ideas. Additionally, when the professor calls on you after the discussion, be sure to share the insights you gained.

- Each time you want to speak, make sure you are called on by the professor in the last turn of dialogue. Otherwise you are not allowed to speak!

- You should respond in the following format:
Action: (an action name, it can be one of [RaiseHand, Listen, Speak])
Action Input: (argument for the action)

Remember to pay attention to the response format instructions, and strictly follow the rules specified above! 
What will ${agent_name} do next?
"""

STUDENT_ROLES: Final[Dict[str, str]] = {
    "Oliver": "You are Oliver, a student curious about Natural Language Processing and you want to learn some basic concepts of NLP. You only have a very basic idea of what NLP is.",
    "Ameliaulr": "You are Ameliaulr, a shy student who struggles to keep up with the pace of the class. You have some background in computer science but find the concepts being taught in this class challenging.",
    "Ethan": "You are Ethan, an experienced software engineer who has worked with machine learning algorithms in the past. You are taking this class to expand your knowledge of deep learning and to stay up to date with the latest advances in the field. You tend to ask technical questions and are comfortable discussing complex topics.",
    "Charlotte": "You are Charlotte, a student who is not majoring in computer science but has a keen interest in AI and its applications. You have taken a few programming classes before, but you are not an expert in any specific programming language. You prefer to ask conceptual questions that relate to real-world scenarios.",
    "Mason": "You are Mason, an undergraduate student majoring in computer science who has taken several classes in machine learning and data analysis. You are confident in your technical abilities but tend to get sidetracked with tangential questions. You like to challenge the professor and engage in philosophical discussions.",
    "Ava": "You are Ava, a mature student who is returning to school after several years in industry. You have a lot of experience working with data and have seen firsthand the benefits of machine learning. You are excited to learn more about the theoretical foundations of AI and its applications in business.",
    "Noah": "You are Noah, a student who is passionate about language and linguistics. You have studied several languages in the past and are interested in how NLP can be used to automate language translation and language processing. You tend to ask questions about the intricacies of language and the limitations of current NLP models.",
    "Emma": "You are Emma, a student who is interested in the ethical and societal implications of AI. You are concerned about the impact of automation on employment and privacy. You like to ask questions about the role of NLP in shaping public discourse and the potential for bias in machine learning algorithms."
}

def parse_action(content: str) -> Dict[str, str]:
    """Parse an Action/Action Input formatted response."""
    action = ""
    action_input = ""
    
    if isinstance(content, str):
        for line in content.splitlines():
            line_strip = line.strip()
            low = line_strip.lower()
            if low.startswith("action:"):
                action = line_strip.split(":", 1)[1].strip()
            elif low.startswith("action input:"):
                action_input = line_strip.split(":", 1)[1].strip()
    elif isinstance(content, dict):
        action = content.get("Action") or content.get("action", "")
        action_input = content.get("Action Input") or content.get("action_input") or content.get("Action_Input", "")
    
    return {"action": action, "action_input": action_input}
def create_classroom_graph(
    model_name: str = "gpt-4o-mini",
    max_turns: int = MAX_TURNS,
    num_students: int = 4  # Use the first N students to keep the run small by default.
) -> RootGraph:
    """Create the classroom simulation graph.

    Args:
        model_name: Model name.
        max_turns: Maximum number of turns.
        num_students: Number of students to include (max 8).

    Returns:
        RootGraph: A built RootGraph instance.
    """
    
    # Clamp student count.
    student_names = list(STUDENT_ROLES.keys())[:num_students]
    
    # Model adapter.
    model = OpenAIModel(
        model_name=model_name,
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL"),
    )
    
    formatter = JsonMessageFormatter()
    
    # Memory.
    professor_memory = HistoryMemory(memory_size=100)
    student_memories = {name: HistoryMemory(memory_size=100) for name in student_names}

    root = RootGraph(name="classroom")
    
    # Main loop.
    main_loop = root.create_node(
        Loop,
        name="classroom_environment",
        max_iterations=max_turns,
        attributes={
            "is_grouped": False,
            "is_grouped_ended": False,
            "current_turn": 0,
            "num_discussion_turns": 4,
            "student_per_group": 4,
            "groups": [],
            "called_student": None
        }
    )
    
    root.edge_from_entry(
        receiver=main_loop,
        keys={"selected": "last message from the previous player"}
    )
    
    root.edge_to_exit(
        sender=main_loop,
        keys={"selected": "last message from the current player"}
    )
    # Pre-step node.
    before_step = main_loop.create_node(
        CustomNode,
        name="before_step"
    )
    
    # Routing switch.
    switch = main_loop.create_node(
        LogicSwitch,
        name="order_logic_switch"
    )
    
    # Professor
    before_professor = main_loop.create_node(
        CustomNode,
        name="before_professor",
        memories=[professor_memory]
    )
    
    professor = main_loop.create_node(
        Agent,
        name="professor",
        model=model,
        instructions=PROFESSOR_PROMPT,
        pull_keys={},
        memories=[professor_memory]
    )
    
    # Students
    students = {}
    before_students = {}
    
    for name in student_names:
        role_desc = STUDENT_ROLES[name]
        prompt = Template(STUDENT_PROMPT_TEMPLATE).substitute(
            role_description=role_desc,
            agent_name=name
        )
        
        before_student = main_loop.create_node(
            CustomNode,
            name=f"before_{name}",
            memories=[student_memories[name]]
        )
        
        student = main_loop.create_node(
            Agent,
            name=name,
            model=model,
            instructions=prompt,
            pull_keys={},
            memories=[student_memories[name]]
        )
        
        before_students[name] = before_student
        students[name] = student
    
    # Post-step node.
    after_step = main_loop.create_node(
        CustomNode,
        name="after_step"
    )
    main_loop.edge_from_controller(
        receiver=before_step,
        keys={"selected": "selected message from the previous player"}
    )
    
    main_loop.create_edge(
        sender=before_step,
        receiver=switch,
        keys={
            "selected": "selected message",
            "env_descriptions": "environment description"
        }
    )
    
    # Switch → Professor
    edge_to_before_professor = main_loop.create_edge(
        sender=switch,
        receiver=before_professor,
        keys={
            "selected": "selected message",
            "env_descriptions": "environment description"
        }
    )
    
    main_loop.create_edge(
        sender=before_professor,
        receiver=professor,
        keys={"env_description": "environment description"}
    )
    
    main_loop.create_edge(
        sender=professor,
        receiver=after_step,
        keys={"professor": "your response"}
    )
    
    # Switch → Students
    edges_to_students = {}
    for name in student_names:
        edge_to_student = main_loop.create_edge(
            sender=switch,
            receiver=before_students[name],
            keys={
                "selected": "selected message",
                "env_descriptions": "environment description"
            }
        )
        edges_to_students[name] = edge_to_student
        
        main_loop.create_edge(
            sender=before_students[name],
            receiver=students[name],
            keys={"env_description": "environment description"}
        )
        
        main_loop.create_edge(
            sender=students[name],
            receiver=after_step,
            keys={name: "your response"}
        )
    
    main_loop.edge_to_controller(
        sender=after_step,
        keys={"selected": "selected message from the previous player"}
    )

    def order_rule(message, attributes) -> List[int]:
        # Determine which participants should speak next.
        is_grouped = attributes.get("is_grouped", False)
        is_grouped_ended = attributes.get("is_grouped_ended", False)
        
        if is_grouped_ended:
            return [0]  # Professor
        
        if is_grouped:
            # Group discussion mode: everyone speaks.
            return list(range(len(student_names) + 1))
        
        # Parse the last selected message.
        message_json = {}
        if isinstance(message, str):
            try:
                message_json = json.loads(message)
            except:
                pass
        elif isinstance(message, dict):
            message_json = message
        
        selected = message_json.get("selected", [])
        
        if len(selected) == 0:
            return [0]  # Professor starts
        
        if len(selected) == 1:
            msg = selected[0]
            speaker = msg.get("speaker", "")
            action = msg.get("action", "")
            
            if speaker.startswith("professor"):
                if action == "CallOn":
                    # Professor called on a student.
                    student_name = msg.get("action_input", "")
                    if student_name in student_names:
                        idx = student_names.index(student_name) + 1
                        attributes["called_student"] = student_name
                        return [idx]
                # Otherwise: anyone can respond.
                return list(range(len(student_names) + 1))
            else:
                # After a student speaks, it's the professor's turn.
                return [0]
        
        return [0]
    
    def professor_rule(message, attributes) -> bool:
        return 0 in order_rule(message, attributes)
    
    switch.condition_binding(professor_rule, edge_to_before_professor)
    
    for i, name in enumerate(student_names):
        def make_student_rule(idx):
            def student_rule(message, attributes) -> bool:
                return (idx + 1) in order_rule(message, attributes)
            return student_rule
        
        switch.condition_binding(make_student_rule(i), edges_to_students[name])
    def before_step_logic(message, attributes):
        # Pre-step: prepare environment descriptions.
        is_grouped = attributes.get("is_grouped", False)
        is_grouped_ended = attributes.get("is_grouped_ended", False)
        
        env_descriptions = [""] * (len(student_names) + 1)
        
        if is_grouped_ended:
            env_descriptions = ["The group discussion is over."] * (len(student_names) + 1)
            attributes["is_grouped_ended"] = False
        elif is_grouped:
            for i in range(len(student_names) + 1):
                if i > 0:
                    env_descriptions[i] = "You are currently having a group discussion. Share your thoughts with other members."
        
        message_json = message if isinstance(message, dict) else (json.loads(message) if message else {})
        message_json["env_descriptions"] = env_descriptions
        
        return message_json
    
    def agent_updator(message, attributes, memories, tools, node):
        # Update agent memory from selected messages.
        message_json = message if isinstance(message, dict) else (json.loads(message) if message else {})
        selected = message_json.get("selected", [])
        
        if memories:
            for msg in selected:
                speaker = msg.get("speaker", "")
                content = msg.get("content", "")
                if content:
                    for memory in memories:
                        memory.insert(speaker, content)
            
            if len(selected) == 0:
                for memory in memories:
                    memory.insert("System", "[Silence]")
        
        env_desc = message_json.get("env_descriptions", [""])[0] if node.name == "before_professor" else ""
        return {"env_description": env_desc}
    
    def selector(message, attributes):
        # Select and normalize messages from all participants.
        message_json = message if isinstance(message, dict) else (json.loads(message) if message else {})
        
        selected_messages = []
        
        for sender, content in message_json.items():
            if sender in ["selected", "env_descriptions", "env_description"]:
                continue
            
            try:
                parsed = parse_action(content)
                action = parsed["action"]
                action_input = parsed["action_input"]
                
                if action:
                    selected_messages.append({
                        "content": content,
                        "speaker": sender,
                        "action": action,
                        "action_input": action_input
                    })
            except:
                pass
        
        return {"selected": selected_messages}
    
    def visible_rule(message, attributes):
        # Apply visibility rules and handle group discussion state transitions.
        message_json = message if isinstance(message, dict) else {}
        selected = message_json.get("selected", [])
        
        # Start group discussion.
        if len(selected) == 1 and selected[0].get("action") == "GroupDiscuss":
            attributes["is_grouped"] = True
            attributes["current_turn"] = 0
        
        # Group discussion turn counter.
        if attributes.get("is_grouped", False):
            attributes["current_turn"] = attributes.get("current_turn", 0) + 1
            if attributes["current_turn"] >= attributes.get("num_discussion_turns", 4):
                attributes["is_grouped_ended"] = True
                attributes["is_grouped"] = False
                attributes["current_turn"] = 0
    
    def after_step_logic(message, attributes, memories=None, tools=None, node=None):
        # Post-step: select messages and update state.
        result = selector(message, attributes)
        visible_rule(result, attributes)
        
        # Print current step selection for debugging.
        selected = result.get("selected", [])
        for msg in selected:
            speaker = msg.get("speaker", "")
            action = msg.get("action", "")
            action_input = msg.get("action_input", "")[:100]
            print(f"[{speaker}] action {action}: {action_input}...")
        
        return result
    
    before_step.set_forward(before_step_logic)
    after_step.set_forward(after_step_logic)
    before_professor.set_forward(agent_updator)
    
    for name in student_names:
        before_students[name].set_forward(agent_updator)
    
    return root
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Run Classroom simulation")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="Model name")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS, help="Maximum turns")
    parser.add_argument("--num-students", type=int, default=4, help="Number of students (max 8)")
    args = parser.parse_args()
    
    print("=" * 80)
    print("🏫 Classroom simulation")
    print("=" * 80)
    print(f"Model: {args.model}")
    print(f"Max turns: {args.max_turns}")
    print(f"Number of students: {args.num_students}")
    print()
    
    graph = create_classroom_graph(
        model_name=args.model,
        max_turns=args.max_turns,
        num_students=args.num_students
    )
    
    graph.build()
    output, attributes = graph.invoke({"selected": []})
    
    print()
    print("=" * 80)
    print("🏁 Simulation completed")
    print("=" * 80)


if __name__ == "__main__":
    main()
