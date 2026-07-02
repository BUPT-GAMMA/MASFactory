from masfactory import Loop, NodeTemplate, HumanFileEditVisual
from .planner_diagnose_loop import PlannerDiagnoseLoop


def terminate_check(messages: dict) -> bool:
    """Stop when user gives no feedback or explicitly agrees."""
    user_advice = messages.get("user_advice", "")
    if not isinstance(user_advice, str):
        user_advice = str(user_advice)
    return (not user_advice.strip()) or ("agree" in user_advice.lower())

PlannerHuman = NodeTemplate(
    HumanFileEditVisual,
    pull_keys={},
    push_keys={},
)

PlannerGraph = NodeTemplate(
    Loop,
    terminate_condition_function=terminate_check,
    pull_keys={"cache_file_path": ""},
    push_keys={},
    nodes=[
        ("planner-diagnose-loop", PlannerDiagnoseLoop),
        ("planner-human", PlannerHuman),
    ],
    edges=[
        (
            "CONTROLLER",
            "planner-diagnose-loop",
            {
                "user_demand": "User demand", 
                "role_list": "Role list",
                "user_advice": "User's feedback",
            },
        ),
        (
            "planner-diagnose-loop",
            "planner-human",
            {
                "aml": "The generated AML workflow topology according to the user's demand and the roles."
            },
        ),
        (
            "planner-human",
            "CONTROLLER",
            {
                "aml": "Edited AML workflow topology.",
                "user_advice": "Do you agree the plan? If you agree, enter AGREE. If you have any comments, please enter your comments."
            }
        ),
        (
            "planner-diagnose-loop",
            "CONTROLLER",
            {
                "aml": "The generated AML workflow topology according to the user's demand and the roles."
            }
        ),
    ],
)

__all__ = [
    "PlannerGraph",
]
