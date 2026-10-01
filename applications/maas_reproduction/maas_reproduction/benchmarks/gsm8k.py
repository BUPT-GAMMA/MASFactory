from __future__ import annotations
import re
from typing import Any
from .base import BaseBenchmark


class GSM8KBenchmark(BaseBenchmark):
    """Last-number extraction with the source's 1e-6 tolerance."""
    @staticmethod
    def extract_number(text: Any) -> float | None:
        matches = re.findall(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?|\d+\.\d+", str(text))
        if not matches:
            return None
        try:
            return float(matches[-1].replace(",", ""))
        except ValueError:
            return None

    def score(self, prediction: str | None, expected_answer: Any, *, context: dict[str, Any] | None = None) -> float:
        expected = self.extract_number(expected_answer)
        actual = self.extract_number(prediction)
        if expected is None or actual is None:
            raise ValueError("unable to extract numeric answer")
        return 1.0 if abs(expected - actual) <= 1e-6 else 0.0


GSM8KScorer = GSM8KBenchmark
__all__ = ["GSM8KBenchmark", "GSM8KScorer"]
