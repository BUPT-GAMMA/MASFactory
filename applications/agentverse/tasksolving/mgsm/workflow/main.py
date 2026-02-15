"""MGSM task workflow graph.

Uses `TaskSolvingPipelineGraph` without local execution (`executor_type="none"`).
"""

from __future__ import annotations

from typing import Any

from masfactory import Model, RootGraph
from masfactory.core.message import LenientJsonMessageFormatter, ParagraphMessageFormatter, TwinsFieldTextFormatter

from applications.agentverse.components.agentverse_vertical_solver_first import (
    AgentverseVerticalSolverFirstDecisionGraph,
)
from applications.agentverse.components.tasksolving.tasksolving_pipeline_graph import TaskSolvingPipelineGraph


def create_mgsm_graph(
    model: Model,
    task: str,
    max_turn: int = 3,
    num_critics: int = 2,
    max_inner_turns: int = 3,
) -> RootGraph:
    """Create the MGSM task graph."""

    root = RootGraph(name="mgsm_task")

    cnt_agents = max(2, int(num_critics) + 1)  # solver + critics

    solver_instructions = (
        "Solve the following math problem:\n"
        "{task_description}\n\n"
        "This math problem can be answered without any extra information. You should not ask for any extra information.\n\n"
        "You are {role_description}. Using the information in the chat history and your knowledge, provide the correct "
        "solution step by step. Your final answer MUST be a single number in the form \\boxed{...} at the end."
    )

    critic_instructions = (
        "You are {role_description}. You are in a discussion group aiming to collaboratively solve:\n"
        "{task_description}\n\n"
        "Compare your reasoning with the latest solution in the chat history and provide critiques only.\n"
        "If you agree the final answer matches yours, end with [Agree]. Otherwise end with [Disagree].\n"
        "Do not ask for extra information."
    )

    solver_config: dict[str, Any] = {
        "role_name": "Math Solver",
        "prepend_prompt_template": solver_instructions,
        "append_prompt_template": "",
        "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
        "model_settings": {"temperature": 0.0},
    }

    critic_configs: list[dict[str, Any]] = []
    for i in range(cnt_agents - 1):
        critic_configs.append(
            {
                "role_name": f"Math Expert {i+1}",
                "prepend_prompt_template": critic_instructions,
                "append_prompt_template": "",
                "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
                "model_settings": {"temperature": 0.0},
            }
        )

    decision_graph_args = {
        "cls": AgentverseVerticalSolverFirstDecisionGraph,
        "name": "mgsm_decision",
        "solver_config": solver_config,
        "critic_configs": critic_configs,
        "model": model,
        "max_inner_turns": int(max_inner_turns),
        "shared_memory": True,
        "attributes": {
            "task_description": task,
            "advice": "",
            "previous_plan": "",
            "has_valid_feedback": True,
        },
    }

    role_assigner_config: dict[str, Any] = {
        "role_name": "Team Leader",
        "prepend_prompt_template": "",
        "append_prompt_template": (
            "You are the leader of a group of experts.\n\n"
            "Task:\n{task_description}\n\n"
            "You can recruit {cnt_critic_agents} experts (solver + critics). What experts will you recruit?\n\n"
            "Return a numbered list of role descriptions only."
        ),
        "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
    }

    evaluator_config: dict[str, Any] = {
        "role_name": "Math Teacher",
        "prepend_prompt_template": "",
        "append_prompt_template": (
            "You are a strict math teacher. Check whether the solution is correct and ends with \\boxed{...}.\n\n"
            "Problem:\n{task_description}\n\n"
            "Solution:\n{solution}\n\n"
            "Return a single JSON object with keys:\n"
            '- "score": 0 or 1\n'
            '- "advice": one-line advice (empty if score=1)\n'
        ),
        "formatters": [ParagraphMessageFormatter(), LenientJsonMessageFormatter()],
        "model_settings": {"temperature": 0.0},
    }

    pipeline = root.create_node(
        TaskSolvingPipelineGraph,
        name="mgsm_pipeline",
        decision_graph_args=decision_graph_args,
        role_assigner_config=role_assigner_config,
        evaluator_config=evaluator_config,
        executor_config=None,
        model=model,
        max_turn=int(max_turn),
        cnt_agents=cnt_agents,
        executor_type="none",
        pull_keys={
            "task_description": "MGSM problem",
            "advice": "Advice from evaluator",
            "previous_plan": "Previous solution",
        },
        push_keys={
            "solution": "Final solution",
            "score": "Evaluator score",
            "advice": "Evaluator advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )

    root.edge_from_entry(
        receiver=pipeline,
        keys={
            "task_description": "MGSM problem",
            "advice": "Advice from evaluator",
            "previous_plan": "Previous solution",
        },
    )
    root.edge_to_exit(
        sender=pipeline,
        keys={
            "solution": "Final solution",
            "score": "Evaluator score",
            "advice": "Evaluator advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )

    root.build()
    return root
