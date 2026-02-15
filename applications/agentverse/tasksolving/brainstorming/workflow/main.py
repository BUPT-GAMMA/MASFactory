"""Brainstorming task workflow graph."""

import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError(f"Cannot locate repo root from: {start}")


repo_root = _find_repo_root(Path(__file__).resolve())
sys.path.insert(0, str(repo_root))

from masfactory import RootGraph, Loop, Agent, CustomNode, Model
from applications.agentverse.components.agentverse_brainstorming_decision import (
    AgentverseBrainstormingDecisionGraph,
)


def create_brainstorming_graph(
    task_description: str,
    model: Model,
    max_turn: int = 3,
    max_inner_turns: int = 0,
    num_critics: int = 4
) -> RootGraph:
    """Build a brainstorming workflow graph.

    Args:
        task_description: The task to brainstorm about.
        model: LLM model instance.
        max_turn: Maximum outer iterations.
        max_inner_turns: Maximum inner iterations (kept for API compatibility).
        num_critics: Number of critic agents.
    """
    root = RootGraph(name="brainstorming_workflow")

    # Role assignment: recruit expert roles for the discussion.
    role_assigner_prompt = f"""You are the leader of a group of experts, now you are faced with a task:

{task_description}

You can recruit {num_critics} expert team members in different regions.
What experts will you recruit to better generate good ideas?

Output format example:
1. an electrical engineer specified in the field of xxx
2. an economist who is good at xxx
3. a lawyer with a good knowledge of xxx
...

You don't have to give the reason."""
    
    role_assigner = root.create_node(
        Agent,
        name="role_assigner",
        instructions=role_assigner_prompt,
        model=model,
        pull_keys={},
        push_keys={}
    )
    
    # Role processor: Convert role list to description string
    def process_roles(messages: dict) -> dict:
        role_list = messages.get("message", "")
        if isinstance(role_list, list):
            role_description = "\n".join([f"{i+1}. {role}" for i, role in enumerate(role_list)])
        else:
            role_description = str(role_list)
        return {
            "role_description": role_description,
            "solution": "",
            "advice": "No advice yet.",
            "evaluation": ""
        }
    
    role_processor = root.create_node(
        CustomNode,
        name="role_processor",
        forward=process_roles,
        pull_keys={},
        push_keys={}
    )
    
    root.edge_from_entry(
        receiver=role_assigner,
        keys={}
    )
    
    root.create_edge(
        sender=role_assigner,
        receiver=role_processor,
        keys={"message": "The list of expert roles"}
    )

    # Main controller loop.
    def check_max_turn(attributes: dict) -> bool:
        return False  # Termination is controlled by Loop.max_iterations.
    
    main_loop = root.create_node(
        Loop,
        name="main_loop",
        max_iterations=max_turn,
        terminate_condition_function=check_max_turn,
        pull_keys=None,  # Inherit all attributes
        push_keys={},
        attributes={
            "task_description": task_description,
            "solution": "",
            "result": "",
            "message": "",
            "advice": "No advice yet.",
            "previous_plan": "No solution yet.",
            "role_description": ""
        }
    )
    
    root.create_edge(
        sender=role_processor,
        receiver=main_loop,
        keys={
            "role_description": "Description of expert roles",
            "solution": "Initial solution (empty)",
            "advice": "Initial advice",
            "evaluation": "Initial evaluation (empty)"
        }
    )

    # Decision graph (brainstorming + summarization).
    solver_instructions = f"""You are a summarizer. 
Your task is to categorize and summarize the ideas in the chat history.
Please add the speaker of each idea to the beginning of the content.

The question of the discussing is to {task_description}. Below is the chat history:

# Output format
1. (Speaker1): (Ideas of Speaker 1 in a single line)
2. (Speaker2): (Ideas of Speaker 2 in a single line)
3. (Speaker3): (Ideas of Speaker 3 in a single line)
...

Please merge all ideas of one speaker into one item."""
    
    # Critic configurations
    critic_configs = []
    for i in range(num_critics):
        critic_prepend = "You are ${role_description}. You are in a discussion group, aiming to ${task_description}."
        critic_append = """Now the group is asking your opinion about it. Based on your knowledge in your field, do you agree that this solution can perfectly solve the problem? Or do you have any ideas to improve it?

- If you thinks it is perfect, use the following output format:
Action: Agree
Action Input: Agree.
(Do not output your reason for agreeing!)

- If you want to give complemented opinions to improve it or to contradict with it, use the following output format:
Action: Disagree
Action Input: (what you want to say in one line)

P.S. Always remember you are ${role_description}!

If no former solution or critic opinions are given, you can just disagree and output your idea freely, based on the expertise of your role.
Remember, the ideas should be specific and detailed enough, not just general opinions."""
        
        critic_configs.append({
            "name": f"Expert_{i+1}",
            "prepend_prompt": critic_prepend,
            "append_prompt": critic_append
        })
    
    decision_graph = main_loop.create_node(
        AgentverseBrainstormingDecisionGraph,
        name="decision_graph",
        solver_role_name="Summarizer",
        solver_instructions=solver_instructions,
        critic_configs=critic_configs,
        model=model,
        summarize_discussion=True,
        pull_keys={
            "task_description": "The task to solve",
            "previous_plan": "Previous solution or plan",
            "advice": "Advice from evaluator",
            "role_description": "Description of expert roles"
        },
        push_keys=None  # Push all outputs to attributes
    )

    # Connect controller to decision_graph for subsequent iterations
    main_loop.edge_from_controller(
        receiver=decision_graph,
        keys={
            "solution": "Previous solution",
            "advice": "Advice from evaluator",
            "evaluation": "Previous evaluation",
            "role_description": "Description of expert roles"
        }
    )

    # Evaluator (LLM): scores and provides one-line advice.
    evaluator_instructions = f"""Your task is to evaluate the ideas in the solution.

The goal is to {task_description}.

Please rate the ideas in the content in the following dimensions:
    1. Comprehensiveness:Are they comprehensive enough to cover all the 
       important aspects a engineering project may have?
    2. Detailedness: Are they detailed enough to be implemented?
    3. Feasibility: Are they reasonable and practical?
    4. Novelty: Are they creative and innovative?

0 means the idea is like random generated ideas,
10 means the idea is perfect in that aspect.

and then in the fifth line of output, give your detailed advice for the solution generators.
You can also give advice to the human resource staff on what experts they should recruit.
Just say the drawbacks of the ideas, no need to do compliments first.

#Output format
You must output in the following format:
1. Comprehensiveness: (a score between 0 and 9)
2. Detailedness: (a score between 0 and 9)
3. Feasibility: (a score between 0 and 9)
4. Novelty: (a score between 0 and 9)
5. Advice: (your advice in one line)

Here is the content you have to evaluate:
${{solution}}"""
    
    evaluator = main_loop.create_node(
        Agent,
        name="evaluator",
        instructions=evaluator_instructions,
        model=model,
        pull_keys={},
        push_keys=None
    )
    
    main_loop.create_edge(
        sender=decision_graph,
        receiver=evaluator,
        keys={"solution": "The generated solution"}
    )

    # Extract advice from evaluator output.
    def extract_advice(messages: dict) -> dict:
        message = messages.get("message", "")
        solution = messages.get("solution", "")
        
        # If message is a dict (from JsonMessageFormatter), extract advice and convert to string
        if isinstance(message, dict):
            advice = message.get("Advice", "")
            # Convert the evaluation dict to a formatted string
            evaluation_str = "\n".join([f"{k}: {v}" for k, v in message.items()])
            return {"advice": advice, "evaluation": evaluation_str, "solution": solution}
        
        # If message is a string, try to extract the "Advice:" line
        if "Advice:" in message or "5." in message:
            lines = message.split("\n")
            for line in lines:
                if "Advice:" in line or (line.strip().startswith("5.") and "Advice" in line):
                    advice = line.split(":", 1)[-1].strip()
                    return {"advice": advice, "evaluation": message, "solution": solution}
        
        return {"advice": message, "evaluation": message, "solution": solution}
    
    advice_extractor = main_loop.create_node(
        CustomNode,
        name="advice_extractor",
        forward=extract_advice,
        pull_keys={},
        push_keys=None
    )
    
    # Connect decision_graph to advice_extractor to pass solution
    main_loop.create_edge(
        sender=decision_graph,
        receiver=advice_extractor,
        keys={"solution": "The generated solution"}
    )
    
    # Connect evaluator to advice_extractor to pass evaluation
    main_loop.create_edge(
        sender=evaluator,
        receiver=advice_extractor,
        keys={"message": "The evaluation result"}
    )

    # Combine outputs for the controller.
    def combine_outputs(messages: dict, attributes: dict) -> dict:
        return {
            "solution": messages.get("solution", ""),
            "advice": messages.get("advice", ""),
            "evaluation": messages.get("evaluation", ""),
            "role_description": attributes.get("role_description", "")
        }
    
    output_combiner = main_loop.create_node(
        CustomNode,
        name="output_combiner",
        forward=combine_outputs,
        pull_keys={"role_description": "Description of expert roles"},
        push_keys={}
    )

    # Connect advice_extractor to output_combiner
    main_loop.create_edge(
        sender=advice_extractor,
        receiver=output_combiner,
        keys={
            "advice": "Advice for next iteration",
            "evaluation": "The evaluation result",
            "solution": "The solution"
        }
    )

    # Connect output_combiner to controller
    main_loop.edge_to_controller(
        sender=output_combiner,
        keys={
            "solution": "The final solution",
            "advice": "Advice for next iteration",
            "evaluation": "The evaluation result",
            "role_description": "Description of expert roles"
        }
    )
    # Main loop -> Exit.
    root.edge_to_exit(
        sender=main_loop,
        keys={
            "solution": "The final solution",
            "evaluation": "The evaluation result"
        }
    )

    return root
