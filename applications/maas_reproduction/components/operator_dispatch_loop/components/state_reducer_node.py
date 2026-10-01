"""The sole state transition seam in the operator dispatch loop."""

from __future__ import annotations

from collections.abc import Mapping

from masfactory.components.custom_node import CustomNode

from applications.maas_reproduction.maas_reproduction.schemas import DispatchState, OperatorResult
from .controller_message import LoopControllerMessage


def reduce_result(previous: DispatchState, result: OperatorResult) -> DispatchState:
    """Return a new state after one operator result; never mutate ``previous``."""
    if not isinstance(previous, DispatchState):
        raise TypeError("previous must be a DispatchState")
    if not isinstance(result, OperatorResult):
        raise TypeError("result must be an OperatorResult")

    candidates = list(previous.candidates)
    for candidate in result.candidates:
        if candidate not in candidates:
            candidates.append(candidate)
    if result.solution is not None and result.solution not in candidates:
        candidates.append(result.solution)

    error_state = previous.error_state
    is_early_stop_control = (
        result.operator_name == "EarlyStop" and result.status == "control"
    )
    if result.status not in {"success", "ok", "completed"} and not is_early_stop_control:
        error_state = {
            **(previous.error_state or {}),
            "operator_name": result.operator_name,
            "status": result.status,
            **result.metadata,
        }

    terminate = previous.termination_requested or is_early_stop_control
    if result.metadata.get("termination_requested") is True:
        terminate = True

    return DispatchState(
        request=previous.request,
        route_plan=previous.route_plan,
        route_cursor=previous.route_cursor + 1,
        current_solution=(result.solution if result.solution is not None else previous.current_solution),
        candidates=tuple(candidates),
        termination_requested=terminate,
        error_state=error_state,
    )


def reduce_operator_result(message: dict, attributes: dict) -> dict:
    previous = attributes.get("dispatch_state")
    if not isinstance(previous, DispatchState):
        raise TypeError("Loop-local dispatch_state must be a DispatchState")
    updated = reduce_result(previous, message["operator_result"])
    control = message.get("loop_control")
    iteration = control.iteration + 1 if isinstance(control, LoopControllerMessage) else 1
    should_continue = (
        not updated.termination_requested
        and updated.route_cursor < len(updated.route_plan.items)
    )
    return {
        "dispatch_state": updated,
        "loop_control": LoopControllerMessage(
            cursor=updated.route_cursor,
            iteration=iteration,
            should_continue=should_continue,
        ),
    }


class StateReducerNode(CustomNode):
    def __init__(self, name: str = "state_reducer") -> None:
        super().__init__(
            name=name,
            forward=reduce_operator_result,
            pull_keys={"dispatch_state": "Current dispatch state."},
            push_keys={"dispatch_state": "Current dispatch state."},
        )


__all__ = ["StateReducerNode", "reduce_operator_result", "reduce_result"]
