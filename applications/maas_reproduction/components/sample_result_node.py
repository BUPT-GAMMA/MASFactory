from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from masfactory.components.custom_node import CustomNode
from applications.maas_reproduction.maas_reproduction.schemas import SampleResult


def _get(value: object, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


class SampleResultNode(CustomNode):
    """Convert internal evaluation/update payloads into a detached public record."""

    def __init__(self, name: str = "sample_result", **kwargs: Any) -> None:
        super().__init__(name=name, forward=self._convert, **kwargs)

    @staticmethod
    def _convert(message: dict[str, object]) -> dict[str, object]:
        evaluation = message.get("evaluation_result")
        update = message.get("update_result", {})
        if evaluation is None:
            raise ValueError("evaluation_result is required")
        policy = _get(evaluation, "policy_log_prob")
        value = None
        if policy is not None:
            try:
                value = float(policy.detach().cpu().item())
            except AttributeError:
                value = float(policy)
        utility = _get(update, "utility")
        result = SampleResult(
            problem_index=int(_get(evaluation, "problem_index", 0)), prediction=_get(evaluation, "prediction"),
            score=_get(evaluation, "score"), cost_delta=_get(evaluation, "cost_delta"),
            status=_get(evaluation, "status", "unknown"), failure_source=_get(evaluation, "failure_source"),
            result_valid=bool(_get(evaluation, "result_valid", False)), cost_reliable=bool(_get(evaluation, "cost_reliable", False)),
            evaluation_reliable=bool(_get(evaluation, "evaluation_reliable", False)), policy_log_prob_value=value,
            utility=utility, update_performed=bool(_get(update, "update_performed", False)),
            skip_reason=_get(update, "skip_reason"), loss_value=_get(update, "loss_value"),
            failure_detail=_failure_detail(evaluation),
        )
        return {"sample_result": result.to_dict()}


def _failure_detail(evaluation: object) -> str | None:
    metadata = _get(evaluation, "execution_metadata", {})
    cost_error = metadata.get("cost_error") if isinstance(metadata, dict) else None
    if cost_error:
        return str(cost_error)[:500]
    error_state = metadata.get("error_state") if isinstance(metadata, dict) else None
    if not isinstance(error_state, dict):
        return None
    stage = error_state.get("stage")
    error_type = error_state.get("error_type")
    message = error_state.get("message")
    operator_name = error_state.get("operator_name")
    status = error_state.get("status")
    parts = [
        str(value)
        for value in (stage, operator_name, status, error_type, message)
        if value
    ]
    return ": ".join(parts)[:500] if parts else None


__all__ = ["SampleResultNode"]
