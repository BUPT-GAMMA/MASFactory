from __future__ import annotations

from masfactory import HumanFileEditVisual, Loop, NodeTemplate

from .profile_designer_agent import ProfileDesignerAgent


def terminate_check(messages: dict) -> bool:
    user_advice: str = messages.get("user_advice", "")
    return (len(user_advice.strip()) == 0) or ("agree" in user_advice.lower())


ProfileHuman = NodeTemplate(
    HumanFileEditVisual,

    pull_keys={},
    push_keys={},
)


ProfileDesignerHumanGraph = NodeTemplate(
    Loop,
    max_iterations=20,
    terminate_condition_function=terminate_check,
    initial_messages={"user_advice": "No advice yet.", "system_advice": "No advice yet."},
    nodes=[
        ("profile_designer_agent", ProfileDesignerAgent),
        ("profile_human", ProfileHuman),
    ],
    edges=[
        (
            "CONTROLLER",
            "profile_designer_agent",
            {
                "user_demand": "User demand",
                "role_list": "Role list",
                "graph_design": "Graph design (topology from planner)",
                "user_advice": "User advice",
                "system_advice": "System advice",
            },
        ),
        (
            "profile_designer_agent",
            "profile_human",
            {"graph_design": "Graph design JSON to review/edit."},
        ),
        (
            "profile_human",
            "CONTROLLER",
            {
                "graph_design": "Edited graph design JSON",
                "user_advice": "Enter AGREE to accept, or write comments to revise.",
            },
        )
    ],
)


__all__ = ["ProfileDesignerHumanGraph"]

