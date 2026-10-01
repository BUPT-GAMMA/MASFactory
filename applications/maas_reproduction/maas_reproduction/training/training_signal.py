"""Single, centralized policy-update eligibility decision."""
from __future__ import annotations

import math
from collections.abc import Mapping
from applications.maas_reproduction.maas_reproduction.schemas import EvaluationResult, TrainingSignal


def build_training_signal(evaluation_result: EvaluationResult | Mapping[str, object]) -> TrainingSignal:
    """Apply the frozen validity/reliability gates and MaAS utility formula."""
    data = evaluation_result if isinstance(evaluation_result, Mapping) else {
        name: getattr(evaluation_result, name)
        for name in ("result_valid", "cost_reliable", "evaluation_reliable", "policy_log_prob", "score", "cost_delta")
    }
    if not bool(data.get("result_valid", False)):
        return TrainingSignal(False, None, "invalid_architecture_result")
    if not bool(data.get("cost_reliable", False)):
        return TrainingSignal(False, None, "unreliable_cost")
    if not bool(data.get("evaluation_reliable", False)):
        return TrainingSignal(False, None, "unreliable_evaluation")
    if data.get("policy_log_prob") is None:
        return TrainingSignal(False, None, "missing_policy_log_prob")
    score, cost = data.get("score"), data.get("cost_delta")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
        return TrainingSignal(False, None, "unreliable_evaluation")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(float(cost)) or float(cost) < 0:
        return TrainingSignal(False, None, "unreliable_cost")
    return TrainingSignal(True, float(score) - 3.0 * float(cost), None)


__all__ = ["build_training_signal"]
