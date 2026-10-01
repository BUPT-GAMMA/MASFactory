"""Dataset scoring seams used by :class:`EvaluatorNode`.

Scorers are deliberately small, synchronous adapters.  They return an
explicit reliability bit so evaluator failures cannot accidentally become a
zero reward (or a trainable sample).
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: float | None
    reliable: bool
    error: str | None = None

    def __post_init__(self) -> None:
        if self.score is not None and (isinstance(self.score, bool) or not isinstance(self.score, (int, float))):
            raise TypeError("score must be a real number or None")
        if self.score is not None and not isfinite(float(self.score)):
            raise ValueError("score must be finite")
        if not isinstance(self.reliable, bool):
            raise TypeError("reliable must be a bool")
        if self.reliable and self.score is None:
            raise ValueError("a reliable score requires a value")
        if not self.reliable and not self.error:
            raise ValueError("an unreliable score requires an error")


class BaseBenchmark:
    """Minimal scorer interface; subclasses implement ``score``."""

    def score(self, prediction: str | None, expected_answer: Any, *, context: dict[str, Any] | None = None) -> float:
        raise NotImplementedError

    def evaluate(self, prediction: str | None, expected_answer: Any, *, context: dict[str, Any] | None = None) -> ScoreResult:
        try:
            if prediction is None or not str(prediction).strip():
                return ScoreResult(None, False, "prediction is empty")
            value = float(self.score(str(prediction), expected_answer, context=context))
            if not isfinite(value):
                return ScoreResult(None, False, "scorer returned a non-finite score")
            return ScoreResult(value, True)
        except Exception as exc:
            return ScoreResult(None, False, f"{type(exc).__name__}: {exc}")


BaseScorer = BaseBenchmark
ScoringResult = ScoreResult
__all__ = ["BaseBenchmark", "BaseScorer", "ScoreResult", "ScoringResult"]
