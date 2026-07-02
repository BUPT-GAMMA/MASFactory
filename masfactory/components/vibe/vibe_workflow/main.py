from __future__ import annotations

from masfactory import Graph, NodeTemplate

from .role_assigner import RoleAssignerGraph
from .planner.planner_graph import PlannerGraph
from .profile_designer import ProfileDesignerHumanGraph


VibeWorkflow = NodeTemplate(
    Graph,
    nodes=[
        ("role-assigner-graph", RoleAssignerGraph),
        ("planner-graph", PlannerGraph),
        ("profile-graph", ProfileDesignerHumanGraph),
    ],
    edges=[
        ("ENTRY", "role-assigner-graph", {"user_demand": ""}),
        ("ENTRY", "planner-graph", {"user_demand": ""}),
        ("ENTRY", "profile-graph", {"user_demand": ""}),
        ("role-assigner-graph", "planner-graph", {"role_list": ""}),
        ("role-assigner-graph", "profile-graph", {"role_list": ""}),
        ("planner-graph", "profile-graph", {"aml": "Workflow AML topology from planner."}),
        (
            "profile-graph",
            "EXIT",
            {"aml": "The generated AML workflow according to the user's demand and the roles."},
        ),
    ],
)


def create_vibe_workflow() -> NodeTemplate[Graph]:
    return VibeWorkflow.clone()


__all__ = ["VibeWorkflow", "create_vibe_workflow"]
