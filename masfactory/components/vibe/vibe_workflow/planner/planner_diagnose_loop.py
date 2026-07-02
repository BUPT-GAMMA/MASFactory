from masfactory import NodeTemplate, Loop
from .planner_agent import PlannerAgent
from .diagnose_node import DiagnoseNode


def _as_bool(value: object) -> bool:
    """Best-effort bool coercion used by loop termination checks."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off", ""}:
            return False
    return bool(value)


def terminate_check(messages: dict, _attributes: dict | None = None) -> bool:
    return not _as_bool(messages.get("diagnose_has_issues", False))


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
                "aml": "The generated AML workflow topology according to the user's demand and the roles.",
            },
        ),
        (
            "planner",
            "CONTROLLER",
            {
                "aml": "The generated AML workflow topology according to the user's demand and the roles.",
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
