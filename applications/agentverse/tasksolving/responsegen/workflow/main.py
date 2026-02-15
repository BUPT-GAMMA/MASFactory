"""ResponseGen task workflow graph.

Generates the next System response; no local execution is performed.
"""

from __future__ import annotations

from typing import Any

from masfactory import Model, RootGraph
from masfactory.core.message import LenientJsonMessageFormatter, ParagraphMessageFormatter, TwinsFieldTextFormatter

from applications.agentverse.components.agentverse_vertical_solver_first import (
    AgentverseVerticalSolverFirstDecisionGraph,
)
from applications.agentverse.components.tasksolving.tasksolving_pipeline_graph import TaskSolvingPipelineGraph


def create_responsegen_graph(
    model: Model,
    max_turn: int = 3,
    num_critics: int = 2,
    max_inner_turns: int = 3,
) -> RootGraph:
    root = RootGraph(name="responsegen_task")

    cnt_agents = max(2, int(num_critics) + 1)

    solver_instructions = (
        "You are {role_description}. Below is a chat history:\n"
        "{task_description}\n\n"
        "Generate the next System response.\n"
        'Rules:\n- Output ONLY ONE line starting with \"System: \"\n- Do not add extra commentary.\n'
    )

    critic_instructions = (
        "You are {role_description}. Review the latest proposed next System response for the chat history:\n"
        "{task_description}\n\n"
        "If it is excellent and follows the format, end with [Agree]. Otherwise give concise advice and end with "
        "[Disagree]."
    )

    solver_config: dict[str, Any] = {
        "role_name": "Response Generator",
        "prepend_prompt_template": solver_instructions,
        "append_prompt_template": "",
        "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
        "model_settings": {"temperature": 0.7},
    }

    critic_configs: list[dict[str, Any]] = []
    for i in range(cnt_agents - 1):
        critic_configs.append(
            {
                "role_name": f"Dialogue Expert {i+1}",
                "prepend_prompt_template": critic_instructions,
                "append_prompt_template": "",
                "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
                "model_settings": {"temperature": 0.0},
            }
        )

    decision_graph_args = {
        "cls": AgentverseVerticalSolverFirstDecisionGraph,
        "name": "responsegen_decision",
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
            "Chat history:\n{task_description}\n\n"
            "Recruit {cnt_critic_agents} experts (solver + critics) to help craft the best next System response.\n\n"
            "Return a numbered list of role descriptions only."
        ),
        "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
    }

    evaluator_config: dict[str, Any] = {
        "role_name": "Dialogue Teacher",
        "prepend_prompt_template": "",
        "append_prompt_template": (
            "You are an experienced dialogue teacher. Judge whether the proposed next System response is appropriate.\n\n"
            "Chat history:\n{task_description}\n\n"
            "Next System response:\n{solution}\n\n"
            "Return a single JSON object with keys:\n"
            '- "score": 0 or 1\n'
            '- "advice": one-line advice (empty if score=1)\n'
        ),
        "formatters": [ParagraphMessageFormatter(), LenientJsonMessageFormatter()],
        "model_settings": {"temperature": 0.0},
    }

    pipeline = root.create_node(
        TaskSolvingPipelineGraph,
        name="responsegen_pipeline",
        decision_graph_args=decision_graph_args,
        role_assigner_config=role_assigner_config,
        evaluator_config=evaluator_config,
        executor_config=None,
        model=model,
        max_turn=int(max_turn),
        cnt_agents=cnt_agents,
        executor_type="none",
        pull_keys={"task_description": "Chat history", "advice": "Advice", "previous_plan": "Previous plan"},
        push_keys={
            "solution": "Next System response",
            "score": "Score",
            "advice": "Advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )

    root.edge_from_entry(
        receiver=pipeline,
        keys={"task_description": "Chat history", "advice": "Advice", "previous_plan": "Previous plan"},
    )
    root.edge_to_exit(
        sender=pipeline,
        keys={
            "solution": "Next System response",
            "score": "Score",
            "advice": "Advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )

    root.build()
    return root
