"""MASFactory node adapting benchmark scorers to the evaluation contract."""
from __future__ import annotations

from typing import Any
from dataclasses import asdict, is_dataclass
from masfactory.components.custom_node import CustomNode
from applications.maas_reproduction.maas_reproduction.schemas import EvaluationResult, FailureSource


def _field(value: object, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


class EvaluatorNode(CustomNode):
    def __init__(self, name: str = "evaluator", scorer: object | None = None, **kwargs: Any) -> None:
        self.scorer = scorer
        super().__init__(name=name, forward=self._evaluate, **kwargs)

    def _evaluate(self, message: dict[str, object]) -> dict[str, object]:
        architecture = message.get("architecture_result")
        context = message.get("evaluation_context")
        valid = bool(_field(architecture, "result_valid", False))
        base = dict(
            problem_index=int(_field(context, "problem_index", _field(architecture, "problem_index", 0))),
            prediction=_field(architecture, "prediction"),
            score=None,
            cost_delta=_field(architecture, "cost_delta"),
            policy_log_prob=_field(architecture, "policy_log_prob"),
            status=_field(architecture, "status", "invalid_architecture_result"),
            failure_source=_field(architecture, "failure_source"),
            result_valid=valid,
            cost_reliable=bool(_field(architecture, "cost_reliable", False)),
            evaluation_reliable=False,
            execution_metadata=dict(_field(architecture, "execution_metadata", {}) or {}),
        )
        if not valid:
            base["failure_source"] = base["failure_source"] or _field(architecture, "failure_source")
            return {"evaluation_result": EvaluationResult(**base)}
        try:
            prediction = base["prediction"]
            expected = _field(context, "expected_answer")
            scorer = self.scorer
            if scorer is None:
                raise ValueError("scorer is required")
            score_context = context if isinstance(context, dict) else (asdict(context) if is_dataclass(context) else None)
            if hasattr(scorer, "evaluate"):
                score_result = scorer.evaluate(prediction, expected, context=score_context)
            elif hasattr(scorer, "score"):
                score_result = scorer.score(prediction, expected, context=score_context)
            elif callable(scorer):
                score_result = scorer(prediction, expected)
            else:
                raise TypeError("scorer must expose evaluate/score or be callable")
            if hasattr(score_result, "score"):
                base["score"] = score_result.score
                reliable = bool(score_result.reliable)
            else:
                base["score"] = float(score_result)
                reliable = True
            base["evaluation_reliable"] = reliable
            if not reliable:
                base["failure_source"] = FailureSource.EVALUATION
                base["status"] = "evaluation_error"
        except Exception:
            base["failure_source"] = FailureSource.EVALUATION
            base["status"] = "evaluation_error"
        return {"evaluation_result": EvaluationResult(**base)}


__all__ = ["EvaluatorNode"]
