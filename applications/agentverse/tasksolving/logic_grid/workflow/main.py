"""Logic Grid task workflow graph.

Solves deductive reasoning puzzles; no local execution is performed.
"""

from __future__ import annotations

from typing import Any

from masfactory import Model, RootGraph
from masfactory.core.message import LenientJsonMessageFormatter, ParagraphMessageFormatter, TwinsFieldTextFormatter

from applications.agentverse.components.agentverse_vertical_solver_first import (
    AgentverseVerticalSolverFirstDecisionGraph,
)
from applications.agentverse.components.tasksolving.tasksolving_pipeline_graph import TaskSolvingPipelineGraph


def create_logic_grid_graph(
    model: Model,
    max_turn: int = 3,
    num_critics: int = 2,
    max_inner_turns: int = 3,
) -> RootGraph:
    root = RootGraph(name="logic_grid_task")

    cnt_agents = max(2, int(num_critics) + 1)

    solver_instructions = (
        "Solve the following logic problem:\n"
        "{task_description}\n\n"
        "This problem can be answered by deductive reasoning. Do not ask for extra information.\n\n"
        "You are {role_description}. Explain your reasoning step by step. Your final answer MUST be a single integer "
        "(choice number) in the form \\boxed{...} at the end."
    )

    critic_instructions = (
        "You are {role_description}. Review the latest solution in the chat history for the logic problem:\n"
        "{task_description}\n\n"
        "If you agree the final \\boxed{...} answer is correct, end with [Agree]. Otherwise give concise critique "
        "and end with [Disagree]."
    )

    solver_config: dict[str, Any] = {
        "role_name": "Logic Solver",
        "prepend_prompt_template": solver_instructions,
        "append_prompt_template": "",
        "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
        "model_settings": {"temperature": 0.0},
    }

    critic_configs: list[dict[str, Any]] = []
    for i in range(cnt_agents - 1):
        critic_configs.append(
            {
                "role_name": f"Logic Expert {i+1}",
                "prepend_prompt_template": critic_instructions,
                "append_prompt_template": "",
                "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
                "model_settings": {"temperature": 0.0},
            }
        )

    decision_graph_args = {
        "cls": AgentverseVerticalSolverFirstDecisionGraph,
        "name": "logic_grid_decision",
        "solver_config": solver_config,
        "critic_configs": critic_configs,
        "model": model,
        "max_inner_turns": int(max_inner_turns),
        "shared_memory": True,
        "attributes": {
            "task_description": "",
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
            "Problem:\n{task_description}\n\n"
            "Recruit {cnt_critic_agents} experts (solver + critics) to solve it. Return a numbered list of role "
            "descriptions only."
        ),
        "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
    }

    evaluator_config: dict[str, Any] = {
        "role_name": "Logic Evaluator",
        "prepend_prompt_template": "",
        "append_prompt_template": (
            "Check whether the solution correctly solves the logic problem and ends with a single integer \\boxed{...}.\n\n"
            "Problem:\n{task_description}\n\n"
            "Solution:\n{solution}\n\n"
            "Return a single JSON object with keys score (0 or 1) and advice (string)."
        ),
        "formatters": [ParagraphMessageFormatter(), LenientJsonMessageFormatter()],
        "model_settings": {"temperature": 0.0},
    }

    pipeline = root.create_node(
        TaskSolvingPipelineGraph,
        name="logic_grid_pipeline",
        decision_graph_args=decision_graph_args,
        role_assigner_config=role_assigner_config,
        evaluator_config=evaluator_config,
        executor_config=None,
        model=model,
        max_turn=int(max_turn),
        cnt_agents=cnt_agents,
        executor_type="none",
        pull_keys={"task_description": "Logic grid problem", "advice": "Advice", "previous_plan": "Previous plan"},
        push_keys={
            "solution": "Solution",
            "score": "Score",
            "advice": "Advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )

    root.edge_from_entry(
        receiver=pipeline,
        keys={"task_description": "Logic grid problem", "advice": "Advice", "previous_plan": "Previous plan"},
    )
    root.edge_to_exit(
        sender=pipeline,
        keys={
            "solution": "Solution",
            "score": "Score",
            "advice": "Advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )

    root.build()
    return root
