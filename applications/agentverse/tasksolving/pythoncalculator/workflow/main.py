"""PythonCalculator task workflow graph.

Builds a `TaskSolvingPipelineGraph` that generates Python code and evaluates it
with an LLM. No local execution is performed (`executor_type="none"`).
"""

from __future__ import annotations

from typing import Any

from masfactory import Model, RootGraph
from masfactory.core.message import LenientJsonMessageFormatter, ParagraphMessageFormatter, TwinsFieldTextFormatter

from applications.agentverse.components.agentverse_vertical_solver_first import (
    AgentverseVerticalSolverFirstDecisionGraph,
)
from applications.agentverse.components.tasksolving.tasksolving_pipeline_graph import TaskSolvingPipelineGraph


def create_pythoncalculator_graph(
    model: Model,
    max_turn: int = 3,
    max_inner_turns: int = 2,
    num_critics: int = 3,
    success_threshold: int = 8,
) -> RootGraph:
    """Build the PythonCalculator task workflow.

    Args:
        model: LLM model instance.
        max_turn: Maximum outer iterations.
        max_inner_turns: Maximum refinement turns inside the decision graph.
        num_critics: Number of critic agents (solver is added automatically).
        success_threshold: Accept when evaluator `score >= success_threshold`.
    """
    root = RootGraph(name="pythoncalculator_task")

    cnt_agents = max(2, int(num_critics) + 1)

    solver_prompt = (
        "You are {role_description}. You are writing Python code to solve the task:\n"
        "{task_description}\n\n"
        "Use the chat history and critiques to improve the solution.\n"
        "Write runnable, self-contained code. Prefer clarity over cleverness.\n"
        "If you include code fences, use ```python.\n"
    )

    critic_prompt = (
        "You are {role_description}. Review the latest code solution for:\n"
        "{task_description}\n\n"
        "If it is solid, correct, and complete, end with [Agree]. Otherwise provide concise, actionable critique "
        "and end with [Disagree]."
    )

    solver_config: dict[str, Any] = {
        "role_name": "Code Writer",
        "prepend_prompt_template": solver_prompt,
        "append_prompt_template": "",
        "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
    }

    critic_configs: list[dict[str, Any]] = []
    for i in range(cnt_agents - 1):
        critic_configs.append(
            {
                "role_name": f"Critic {i+1}",
                "prepend_prompt_template": critic_prompt,
                "append_prompt_template": "",
                "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
            }
        )

    decision_graph_args = {
        "cls": AgentverseVerticalSolverFirstDecisionGraph,
        "name": "pythoncalculator_decision",
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
            "Task:\n{task_description}\n\n"
            "Recruit {cnt_critic_agents} experts (solver + critics) to write high-quality Python code.\n\n"
            "Return a numbered list of role descriptions only."
        ),
        "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
    }

    evaluator_config: dict[str, Any] = {
        "role_name": "Code Reviewer",
        "prepend_prompt_template": "",
        "append_prompt_template": (
            "You are a strict code reviewer. Evaluate the proposed solution for the task:\n"
            "{task_description}\n\n"
            "Solution:\n{solution}\n\n"
            "Return a single JSON object with keys:\n"
            '- "score": an integer from 0 to 9 (higher is better)\n'
            '- "advice": one-line advice to improve the solution\n'
        ),
        "formatters": [ParagraphMessageFormatter(), LenientJsonMessageFormatter()],
        "model_settings": {"temperature": 0.0},
    }

    pipeline = root.create_node(
        TaskSolvingPipelineGraph,
        name="pythoncalculator_pipeline",
        decision_graph_args=decision_graph_args,
        role_assigner_config=role_assigner_config,
        evaluator_config=evaluator_config,
        executor_config=None,
        model=model,
        max_turn=int(max_turn),
        cnt_agents=cnt_agents,
        executor_type="none",
        success_threshold=int(success_threshold),
        pull_keys={"task_description": "Task description", "advice": "Advice", "previous_plan": "Previous plan"},
        push_keys={
            "solution": "Final solution",
            "score": "Score",
            "advice": "Advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )

    root.edge_from_entry(
        receiver=pipeline,
        keys={"task_description": "Task description", "advice": "Advice", "previous_plan": "Previous plan"},
    )
    root.edge_to_exit(
        sender=pipeline,
        keys={
            "solution": "Final solution",
            "score": "Score",
            "advice": "Advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )

    root.build()
    return root
