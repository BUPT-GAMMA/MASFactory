"""Route cursor for the native MaAS dispatch loop."""

from __future__ import annotations

from collections.abc import Mapping

from masfactory.components.custom_node import CustomNode

from applications.maas_reproduction.maas_reproduction.schemas import DispatchState, OperatorInvocation


def route_cursor_forward(message: dict, attributes: dict) -> dict:
    """Create one immutable operator invocation from Loop-local state."""
    if "loop_control" not in message:
        raise KeyError("loop_control is required")
    state = attributes.get("dispatch_state")
    if not isinstance(state, DispatchState):
        raise TypeError("Loop-local dispatch_state must be a DispatchState")
    if state.route_cursor >= len(state.route_plan.items):
        raise IndexError("route_cursor is past the end of the route plan")

    item = state.route_plan.items[state.route_cursor]
    invocation = OperatorInvocation(
        sequence_index=item.sequence_index,
        layer_index=item.layer_index,
        position=item.position,
        operator_name=item.operator_name,
        problem=state.request.problem,
        entry_point=state.request.entry_point or "",
        current_solution=state.current_solution or "",
        candidates=state.candidates,
    )
    return {"operator_invocation": invocation}


class RouteCursorNode(CustomNode):
    """Expose the current route item without mutating canonical state."""

    def __init__(self, name: str = "route_cursor") -> None:
        super().__init__(
            name=name,
            forward=route_cursor_forward,
            pull_keys={"dispatch_state": "Current dispatch state."},
            push_keys={},
        )


__all__ = ["RouteCursorNode", "route_cursor_forward"]
