from masfactory import NodeTemplate,Loop
from .planner_agent import PlannerAgent
from .diagnose_node import DiagnoseNode
def terminate_check(messages: dict, _attributes: dict | None = None) -> bool:
    return not bool(messages.get("diagnose_has_issues", False))


PlannerDiagnoseLoop = NodeTemplate(
    Loop,
    max_iterations=2,
    terminate_condition_function=terminate_check,
    initial_messages={"system_advice": "No advice yet.", "diagnose_has_issues": True},
    nodes=[
        ("planner", PlannerAgent),
        ("diagnose_node", DiagnoseNode),
    ],
    edges=[
        (
            "CONTROLLER",
            "planner",
            {
                "user_demand": "User demand",
                "role_list": "Available role list",
                "system_advice": "No system advice yet.",
                "user_advice":"No user advice yet."
            },
        ),
        (
            "planner",
            "diagnose_node",
            {
                "graph_design": "The generated graph design accroding to the user's demand and the roles.",
            },
        ),
        (
            "planner",
            "CONTROLLER",
            {
                "graph_design": "The generated graph design accroding to the user's demand and the roles.",
            },
        ),
        (
            "diagnose_node",
            "CONTROLLER",
            {
                "system_advice": "",
                "diagnose_has_issues": "Whether there are validation issues",
                # "diagnose_issue_count": "How many issues found",
            },
        ),
    ],
)


__all__ = [
    "PlannerDiagnoseLoop",
]
