"""Finalize a dispatch state into the pre-evaluation architecture contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from masfactory.components.custom_node import CustomNode

from applications.maas_reproduction.maas_reproduction.schemas import (
    ArchitectureResult,
    CostResult,
    DispatchState,
    FailureSource,
)


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def finalize_architecture_result(message: dict[str, Any], attributes: dict[str, Any]) -> dict[str, Any]:
    state = message.get("dispatch_state", attributes.get("dispatch_state"))
    completion = message.get("completion_result")
    tracker = attributes.get("cost_tracker") or message.get("cost_tracker")
    before = attributes.get("cost_before", message.get("cost_before"))

    prediction = _value(completion, "prediction")
    if prediction is None and isinstance(state, DispatchState):
        prediction = state.current_solution or (state.candidates[-1] if state.candidates else None)

    # Bootstrap/Loop failures can arrive beside the business state when no
    # DispatchState exists.  They must remain visible at this seam instead of
    # being silently converted into an unattributed invalid result.
    error_state = (
        state.error_state if isinstance(state, DispatchState) else None
    ) or message.get("error_state")
    failure = (
        _value(completion, "failure_source")
        or message.get("failure_source")
        or _value(error_state, "failure_source")
    )
    try:
        failure_source = FailureSource(failure) if failure is not None else None
    except (TypeError, ValueError):
        failure_source = FailureSource.ROUTE_EXECUTION
    if failure_source is None and error_state:
        # A valid fallback solution may coexist with a non-success operator
        # result. Preserve that provenance instead of emitting a bare
        # recoverable_failure with no source.
        failure_source = FailureSource.ROUTE_EXECUTION

    result_valid = isinstance(state, DispatchState) and bool(prediction and str(prediction).strip())
    status = _value(completion, "status") or ("success" if result_valid and not error_state else "recoverable_failure" if result_valid else "invalid_result")

    cost = CostResult(None, False, "cost tracker unavailable")
    if tracker is not None and callable(getattr(tracker, "snapshot", None)) and callable(getattr(tracker, "delta", None)):
        try:
            after = tracker.snapshot()
            if before is not None:
                measured = tracker.delta(before, after)
                cost = measured if isinstance(measured, CostResult) else CostResult(float(measured), True)
            else:
                cost = CostResult(None, False, "missing cost_before snapshot")
        except Exception as exc:  # cost failures are data, not graph failures
            cost = CostResult(None, False, f"cost snapshot failed: {type(exc).__name__}: {exc}")
    elif isinstance(message.get("cost_result"), CostResult):
        cost = message["cost_result"]

    if not cost.reliable:
        failure_source = failure_source or FailureSource.INFRASTRUCTURE
        if status == "success":
            status = "cost_error"

    route_metadata: dict[str, Any] = {}
    execution_metadata: dict[str, Any] = {"cost_error": cost.error} if cost.error else {}
    if isinstance(state, DispatchState):
        route_metadata = {
            "route_length": len(state.route_plan.items),
            "route_cursor": state.route_cursor,
            "termination_requested": state.termination_requested,
        }
        if error_state:
            execution_metadata["error_state"] = dict(error_state)
    elif isinstance(error_state, Mapping):
        # Bootstrap failures intentionally have no DispatchState.  Preserve
        # their structured, non-sensitive diagnostic instead of dropping it
        # at the finalization seam.
        execution_metadata["error_state"] = dict(error_state)
    completion_metadata = _value(completion, "metadata")
    if isinstance(completion_metadata, Mapping):
        execution_metadata.update(dict(completion_metadata))

    result = ArchitectureResult(
        prediction=str(prediction) if prediction is not None else None,
        cost_delta=cost.value,
        policy_log_prob=(state.route_plan.policy_log_prob if isinstance(state, DispatchState) else None),
        status=str(status),
        failure_source=failure_source,
        result_valid=result_valid,
        cost_reliable=cost.reliable,
        route_metadata=route_metadata,
        execution_metadata=execution_metadata,
    )
    return {"architecture_result": result}


class FinalizeArchitectureResultNode(CustomNode):
    """Convert final dispatch state to ``ArchitectureResult`` without detaching policy tensors."""

    def __init__(self, name: str = "finalize_architecture_result", *, cost_tracker: Any = None, **kwargs: Any) -> None:
        attributes = dict(kwargs.pop("attributes", {}) or {})
        if cost_tracker is not None:
            attributes["cost_tracker"] = cost_tracker
        super().__init__(
            name=name,
            forward=finalize_architecture_result,
            # Cost baseline is an execution-local attribute explicitly pulled
            # from the parent ArchitectureExecGraph; no other attributes are
            # inherited.
            pull_keys={"cost_before": "Per-invocation cost baseline."},
            push_keys={},
            attributes=attributes,
            **kwargs,
        )


__all__ = ["FinalizeArchitectureResultNode", "finalize_architecture_result"]
