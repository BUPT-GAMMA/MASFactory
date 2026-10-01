"""Immutable schemas at the planning, execution, evaluation, and training seams.

The module validates only the contracts frozen for Tasks 0 and 1.  Operator-
specific payloads and MASFactory runtime objects deliberately stay outside it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from numbers import Real
from typing import TYPE_CHECKING, Any, Mapping, Sequence, TypeAlias

from .contracts import EARLY_STOP_OPERATOR, TRAINING_SKIP_REASONS

if TYPE_CHECKING:
    from torch import Tensor

    PolicyLogProb: TypeAlias = Tensor
else:
    # Do not import torch merely to construct message schemas.  The live value
    # is carried through by identity so validation cannot detach autograd.
    PolicyLogProb: TypeAlias = Any


class FailureSource(str, Enum):
    """Where a failure occurred; never an input to utility calculation."""

    PLANNING = "planning"
    BOOTSTRAP = "bootstrap"
    ROUTE_EXECUTION = "route_execution"
    EVALUATION = "evaluation"
    INFRASTRUCTURE = "infrastructure"


def _require_bool(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool")


def _require_non_negative_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_non_empty_text(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str")
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


def _require_optional_text(value: object, name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} must be a str or None")


def _finite_float(value: object, name: str, *, optional: bool) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        suffix = " or None" if optional else ""
        raise TypeError(f"{name} must be a real number{suffix}")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence of strings")
    normalized = tuple(value)
    if any(not isinstance(item, str) for item in normalized):
        raise TypeError(f"every item in {name} must be a str")
    return normalized


def _mapping_copy(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"every key in {name} must be a str")
    return dict(value)


def _failure_source(value: object) -> FailureSource | None:
    if value is None or isinstance(value, FailureSource):
        return value
    if isinstance(value, str):
        try:
            return FailureSource(value)
        except ValueError as exc:
            raise ValueError(f"unknown failure_source: {value!r}") from exc
    raise TypeError("failure_source must be a FailureSource, str, or None")


@dataclass(frozen=True, slots=True)
class ArchitectureRequest:
    """Execution-only sample input; an expected answer cannot cross this seam."""

    problem: str
    problem_index: int
    entry_point: str = ""

    def __post_init__(self) -> None:
        _require_non_empty_text(self.problem, "problem")
        _require_non_negative_int(self.problem_index, "problem_index")
        if not isinstance(self.entry_point, str):
            raise TypeError("entry_point must be a str")


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """Evaluator-only input and the sole schema allowed to carry an answer key."""

    problem: str
    problem_index: int
    expected_answer: Any
    entry_point: str = ""
    test: str | None = None
    canonical_solution: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_text(self.problem, "problem")
        _require_non_negative_int(self.problem_index, "problem_index")
        if not isinstance(self.entry_point, str):
            raise TypeError("entry_point must be a str")
        _require_optional_text(self.test, "test")
        _require_optional_text(self.canonical_solution, "canonical_solution")


@dataclass(frozen=True, slots=True)
class RouteItem:
    """One operator or deterministic control marker in a flattened route."""

    sequence_index: int
    layer_index: int
    position: int
    operator_name: str
    is_control_marker: bool = False

    def __post_init__(self) -> None:
        _require_non_negative_int(self.sequence_index, "sequence_index")
        _require_non_negative_int(self.layer_index, "layer_index")
        _require_non_negative_int(self.position, "position")
        _require_non_empty_text(self.operator_name, "operator_name")
        _require_bool(self.is_control_marker, "is_control_marker")
        is_early_stop = self.operator_name == EARLY_STOP_OPERATOR
        if self.is_control_marker != is_early_stop:
            raise ValueError("EarlyStop is the only control marker and must be marked")


@dataclass(frozen=True, slots=True)
class RoutePlan:
    """The sole policy decision, with its live aggregate log-probability."""

    items: tuple[RouteItem, ...]
    policy_log_prob: PolicyLogProb

    def __post_init__(self) -> None:
        if isinstance(self.items, (str, bytes)) or not isinstance(self.items, Sequence):
            raise TypeError("items must be a sequence of RouteItem values")
        normalized_items = tuple(self.items)
        current_layer = -1
        expected_position = 0
        for index, item in enumerate(normalized_items):
            if not isinstance(item, RouteItem):
                raise TypeError("every route item must be a RouteItem")
            if item.sequence_index != index:
                raise ValueError("RouteItem.sequence_index must be contiguous from zero")
            if item.layer_index == current_layer:
                if item.position != expected_position:
                    raise ValueError(
                        "RoutePlan positions must be contiguous within each layer"
                    )
            elif item.layer_index == current_layer + 1:
                current_layer = item.layer_index
                expected_position = 0
                if item.position != expected_position:
                    raise ValueError(
                        "RoutePlan positions must start at zero for each layer"
                    )
            else:
                raise ValueError("RoutePlan items must be layer-major with no gaps")
            expected_position += 1
        if self.policy_log_prob is None:
            raise ValueError("policy_log_prob is required for a valid RoutePlan")
        object.__setattr__(self, "items", normalized_items)


@dataclass(frozen=True, slots=True)
class DispatchState:
    """Minimal immutable state consumed by the operator dispatch loop."""

    request: ArchitectureRequest
    route_plan: RoutePlan
    route_cursor: int = 0
    current_solution: str | None = None
    candidates: tuple[str, ...] = ()
    termination_requested: bool = False
    error_state: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, ArchitectureRequest):
            raise TypeError("request must be an ArchitectureRequest")
        if not isinstance(self.route_plan, RoutePlan):
            raise TypeError("route_plan must be a RoutePlan")
        _require_non_negative_int(self.route_cursor, "route_cursor")
        _require_optional_text(self.current_solution, "current_solution")
        object.__setattr__(self, "candidates", _string_tuple(self.candidates, "candidates"))
        _require_bool(self.termination_requested, "termination_requested")
        if self.error_state is not None:
            object.__setattr__(
                self, "error_state", _mapping_copy(self.error_state, "error_state")
            )


@dataclass(frozen=True, slots=True)
class OperatorInvocation:
    """Read-only input snapshot for exactly one route item execution."""

    sequence_index: int
    layer_index: int
    position: int
    operator_name: str
    problem: str
    entry_point: str = ""
    current_solution: str = ""
    candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_negative_int(self.sequence_index, "sequence_index")
        _require_non_negative_int(self.layer_index, "layer_index")
        _require_non_negative_int(self.position, "position")
        _require_non_empty_text(self.operator_name, "operator_name")
        _require_non_empty_text(self.problem, "problem")
        if not isinstance(self.entry_point, str):
            raise TypeError("entry_point must be a str")
        if not isinstance(self.current_solution, str):
            raise TypeError("current_solution must be a str")
        object.__setattr__(self, "candidates", _string_tuple(self.candidates, "candidates"))


@dataclass(frozen=True, slots=True)
class OperatorResult:
    """Structured result of one operator, including recoverable failures."""

    operator_name: str
    status: str
    solution: str | None = None
    candidates: tuple[str, ...] = ()
    code: str | None = None
    execution_output: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty_text(self.operator_name, "operator_name")
        _require_non_empty_text(self.status, "status")
        _require_optional_text(self.solution, "solution")
        object.__setattr__(self, "candidates", _string_tuple(self.candidates, "candidates"))
        _require_optional_text(self.code, "code")
        _require_optional_text(self.execution_output, "execution_output")
        object.__setattr__(self, "metadata", _mapping_copy(self.metadata, "metadata"))


@dataclass(frozen=True, slots=True)
class CostResult:
    """A per-sample cost delta together with an explicit trust decision."""

    value: float | None
    reliable: bool
    error: str | None = None

    def __post_init__(self) -> None:
        normalized_value = _finite_float(self.value, "value", optional=True)
        object.__setattr__(self, "value", normalized_value)
        _require_bool(self.reliable, "reliable")
        _require_optional_text(self.error, "error")
        if self.reliable:
            if normalized_value is None or normalized_value < 0.0:
                raise ValueError("reliable cost requires a finite, non-negative value")
            if self.error is not None:
                raise ValueError("reliable cost cannot carry an error")
        elif self.error is None or not self.error.strip():
            raise ValueError("unreliable cost requires an error")


@dataclass(frozen=True, slots=True)
class ArchitectureResult:
    """Final execution result before dataset-specific evaluation."""

    prediction: str | None
    cost_delta: float | None
    policy_log_prob: PolicyLogProb | None
    status: str
    failure_source: FailureSource | None
    result_valid: bool
    cost_reliable: bool
    route_metadata: dict[str, Any] = field(default_factory=dict)
    execution_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_optional_text(self.prediction, "prediction")
        normalized_cost = _finite_float(self.cost_delta, "cost_delta", optional=True)
        object.__setattr__(self, "cost_delta", normalized_cost)
        _require_non_empty_text(self.status, "status")
        object.__setattr__(self, "failure_source", _failure_source(self.failure_source))
        _require_bool(self.result_valid, "result_valid")
        _require_bool(self.cost_reliable, "cost_reliable")
        if self.result_valid and (self.prediction is None or not self.prediction.strip()):
            raise ValueError("a valid architecture result requires a non-empty prediction")
        if self.cost_reliable and (normalized_cost is None or normalized_cost < 0.0):
            raise ValueError("reliable cost requires a finite, non-negative cost_delta")
        object.__setattr__(
            self, "route_metadata", _mapping_copy(self.route_metadata, "route_metadata")
        )
        object.__setattr__(
            self,
            "execution_metadata",
            _mapping_copy(self.execution_metadata, "execution_metadata"),
        )


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Architecture result enriched with a dataset score and reliability."""

    problem_index: int
    prediction: str | None
    score: float | None
    cost_delta: float | None
    policy_log_prob: PolicyLogProb | None
    status: str
    failure_source: FailureSource | None
    result_valid: bool
    cost_reliable: bool
    evaluation_reliable: bool
    execution_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_negative_int(self.problem_index, "problem_index")
        _require_optional_text(self.prediction, "prediction")
        normalized_score = _finite_float(self.score, "score", optional=True)
        normalized_cost = _finite_float(self.cost_delta, "cost_delta", optional=True)
        object.__setattr__(self, "score", normalized_score)
        object.__setattr__(self, "cost_delta", normalized_cost)
        _require_non_empty_text(self.status, "status")
        object.__setattr__(self, "failure_source", _failure_source(self.failure_source))
        _require_bool(self.result_valid, "result_valid")
        _require_bool(self.cost_reliable, "cost_reliable")
        _require_bool(self.evaluation_reliable, "evaluation_reliable")
        object.__setattr__(self, "execution_metadata", _mapping_copy(self.execution_metadata, "execution_metadata"))
        if self.result_valid and (self.prediction is None or not self.prediction.strip()):
            raise ValueError("a valid architecture result requires a non-empty prediction")
        if self.cost_reliable and (normalized_cost is None or normalized_cost < 0.0):
            raise ValueError("reliable cost requires a finite, non-negative cost_delta")
        if self.evaluation_reliable:
            if not self.result_valid:
                raise ValueError("an invalid architecture result cannot be reliably evaluated")
            if normalized_score is None:
                raise ValueError("reliable evaluation requires a finite score")


@dataclass(frozen=True, slots=True)
class TrainingSignal:
    """The sole policy-update eligibility decision and optional utility."""

    should_update: bool
    utility: float | None
    skip_reason: str | None

    def __post_init__(self) -> None:
        _require_bool(self.should_update, "should_update")
        normalized_utility = _finite_float(self.utility, "utility", optional=True)
        object.__setattr__(self, "utility", normalized_utility)
        _require_optional_text(self.skip_reason, "skip_reason")
        if self.should_update:
            if normalized_utility is None:
                raise ValueError("an update requires utility")
            if self.skip_reason is not None:
                raise ValueError("an update cannot have a skip_reason")
        else:
            if normalized_utility is not None:
                raise ValueError("a skipped update cannot carry utility")
            if self.skip_reason is None or not self.skip_reason.strip():
                raise ValueError("a skipped update requires a skip_reason")
            if self.skip_reason not in TRAINING_SKIP_REASONS:
                raise ValueError(f"unknown training skip_reason: {self.skip_reason!r}")


@dataclass(frozen=True, slots=True)
class SampleResult:
    """Detached, JSON-ready per-sample result retained by DatasetRunner."""

    problem_index: int
    prediction: str | None
    score: float | None
    cost_delta: float | None
    status: str
    failure_source: FailureSource | None
    result_valid: bool
    cost_reliable: bool
    evaluation_reliable: bool
    policy_log_prob_value: float | None
    utility: float | None
    update_performed: bool
    skip_reason: str | None
    loss_value: float | None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        _require_non_negative_int(self.problem_index, "problem_index")
        _require_optional_text(self.prediction, "prediction")
        normalized_score = _finite_float(self.score, "score", optional=True)
        normalized_cost = _finite_float(self.cost_delta, "cost_delta", optional=True)
        normalized_log_prob = _finite_float(
            self.policy_log_prob_value, "policy_log_prob_value", optional=True
        )
        normalized_utility = _finite_float(self.utility, "utility", optional=True)
        normalized_loss = _finite_float(self.loss_value, "loss_value", optional=True)
        object.__setattr__(self, "score", normalized_score)
        object.__setattr__(self, "cost_delta", normalized_cost)
        object.__setattr__(self, "policy_log_prob_value", normalized_log_prob)
        object.__setattr__(self, "utility", normalized_utility)
        object.__setattr__(self, "loss_value", normalized_loss)
        _require_optional_text(self.failure_detail, "failure_detail")
        _require_non_empty_text(self.status, "status")
        object.__setattr__(self, "failure_source", _failure_source(self.failure_source))
        _require_bool(self.result_valid, "result_valid")
        _require_bool(self.cost_reliable, "cost_reliable")
        _require_bool(self.evaluation_reliable, "evaluation_reliable")
        _require_bool(self.update_performed, "update_performed")
        _require_optional_text(self.skip_reason, "skip_reason")
        if self.result_valid and (self.prediction is None or not self.prediction.strip()):
            raise ValueError("a valid architecture result requires a non-empty prediction")
        if self.cost_reliable and (normalized_cost is None or normalized_cost < 0.0):
            raise ValueError("reliable cost requires a finite, non-negative cost_delta")
        if self.evaluation_reliable and (not self.result_valid or normalized_score is None):
            raise ValueError("reliable evaluation requires a valid result and finite score")

    def to_dict(self) -> dict[str, Any]:
        """Return a public record containing no live policy Tensor."""

        return {
            "problem_index": self.problem_index,
            "prediction": self.prediction,
            "score": self.score,
            "cost_delta": self.cost_delta,
            "status": self.status,
            "failure_source": (
                self.failure_source.value if self.failure_source is not None else None
            ),
            "result_valid": self.result_valid,
            "cost_reliable": self.cost_reliable,
            "evaluation_reliable": self.evaluation_reliable,
            "policy_log_prob_value": self.policy_log_prob_value,
            "utility": self.utility,
            "update_performed": self.update_performed,
            "skip_reason": self.skip_reason,
            "loss_value": self.loss_value,
            "failure_detail": self.failure_detail,
        }


__all__ = [
    "ArchitectureRequest",
    "ArchitectureResult",
    "CostResult",
    "DispatchState",
    "EvaluationContext",
    "EvaluationResult",
    "FailureSource",
    "OperatorInvocation",
    "OperatorResult",
    "PolicyLogProb",
    "RouteItem",
    "RoutePlan",
    "SampleResult",
    "TrainingSignal",
]
