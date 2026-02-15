from __future__ import annotations

from masfactory import RootGraph

from .role_assigner import RoleAssignerGraph
from .planner.planner_graph import PlannerGraph
from .profile_designer import ProfileDesignerHumanGraph

VibeWorkflow = RootGraph(
    "VibeWorkflow",
    nodes=[
        ("role-assigner-graph",RoleAssignerGraph),
        ("planner-graph",PlannerGraph),
        ("profile-graph",ProfileDesignerHumanGraph),
    ],
    edges=[
        ("ENTRY","role-assigner-graph",{"user_demand":""}),
        ("ENTRY","planner-graph",{"user_demand":""}),
        ("ENTRY","profile-graph",{"user_demand":""}),
        
        ("role-assigner-graph","planner-graph", {"role_list":""}),
        ("role-assigner-graph","profile-graph", {"role_list":""}),
        ("planner-graph","profile-graph",{"graph_design":"Your new design of graph."}),
        ("profile-graph","EXIT",{"graph_design":"The generated graph design accroding to the user's demand and the roles."})
    ],
)

__all__ = ["VibeWorkflow"]
