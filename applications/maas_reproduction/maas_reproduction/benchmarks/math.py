from __future__ import annotations
import re
from math import isclose
from typing import Any
from .base import BaseBenchmark


class MATHBenchmark(BaseBenchmark):
    @staticmethod
    def extract_model_answer(text: Any) -> str:
        matches = re.findall(r"\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}", str(text), re.DOTALL)
        if matches:
            return matches[-1].strip()
        sentences = [s.strip() for s in re.split(r"(?<!\d)[.!?]\s+", str(text)) if s.strip()]
        return sentences[-1] if sentences else ""

    @staticmethod
    def _number(value: Any) -> float | None:
        text = str(value).replace(",", "").strip()
        try:
            if text.endswith("%"):
                return float(text[:-1].rstrip("\\")) / 100
            return float(text)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _source_equal(cls, actual: str, expected: str) -> bool:
        """Preserve the original MaAS comparison before applying extensions."""
        if actual == expected:
            return True
        a, b = cls._number(actual), cls._number(expected)
        if a is not None and b is not None and isclose(a, b, abs_tol=1e-3):
            return True

        try:
            from sympy import N, simplify
            from sympy.parsing.latex import parse_latex
            from sympy.parsing.sympy_parser import parse_expr
        except ImportError as exc:
            raise RuntimeError(
                "MATH benchmark requires sympy==1.13.1; install the project dependencies."
            ) from exc

        def parse(value: str):
            for parser in (parse_latex, parse_expr):
                try:
                    return parser(value)
                except Exception:
                    pass
            return value

        parsed_actual, parsed_expected = parse(actual), parse(expected)
        try:
            if simplify(parsed_actual - parsed_expected) == 0:
                return True
        except Exception:
            pass
        try:
            if isclose(float(N(parsed_actual)), float(N(parsed_expected)), abs_tol=1e-3):
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _labeled_answer_candidates(text: Any) -> tuple[str, ...]:
        """Return explicit final-answer lines without guessing from reasoning text."""
        matches = re.findall(
            r"(?im)(?:final\s+answer|answer)\s*[:=]\s*([^\r\n]+)",
            str(text),
        )
        return tuple(match.strip() for match in matches if match.strip())

    @staticmethod
    def _normalize_fallback(value: str) -> str:
        """Normalize common model formatting only after source MaAS rejects it."""
        text = str(value).strip()
        text = re.sub(r"^[`*_~\s]+|[`*_~\s]+$", "", text).strip()
        text = re.sub(r"^\s*[A-Za-z][A-Za-z0-9_]*\s*=\s*", "", text)
        text = text.replace(r"\dfrac", r"\frac")
        # TeX accepts \sqrt3 as the square root of the next token, while
        # SymPy's LaTeX parser silently reads it as a plain leading number.
        text = re.sub(r"\\sqrt\s*([A-Za-z0-9])", r"\\sqrt{\1}", text)
        text = re.sub(r"\^\s*\\circ\b", "", text)
        # Dataset references often keep units inside the answer box.  Strip
        # only a trailing text unit, never arbitrary prose inside an answer.
        text = re.sub(r"\\(?:text|mathrm)\{[^{}]*\}\s*$", "", text).strip()
        text = text.strip("`*_~ ").rstrip(".,;:").strip()
        return text

    @staticmethod
    def _percent_context(context: dict[str, Any] | None, expected_answer: Any) -> bool:
        problem = "" if not context else str(context.get("problem", ""))
        evidence = f"{problem}\n{expected_answer}"
        return bool(re.search(r"(?i)(?:\bpercent(?:age)?\b|\\?%)", evidence))

    @classmethod
    def _percent_points_equal(cls, actual: str, expected: str) -> bool:
        if "%" not in actual and r"\%" not in actual and "%" not in expected and r"\%" not in expected:
            return False

        def points(value: str) -> float | None:
            value = value.replace(r"\%", "%").strip()
            if value.endswith("%"):
                value = value[:-1].strip()
            try:
                return float(value.replace(",", ""))
            except ValueError:
                return None

        a, b = points(actual), points(expected)
        return a is not None and b is not None and isclose(a, b, abs_tol=1e-3)

    def score(self, prediction: str | None, expected_answer: Any, *, context: dict[str, Any] | None = None) -> float:
        actual = self.extract_model_answer(prediction)
        expected = self.extract_model_answer(expected_answer)
        # This first pass is deliberately identical to source MaAS semantics.
        # Enhancements below are fallback-only, so an existing reproduction
        # success can never be turned into a failure.
        if self._source_equal(actual, expected):
            return 1.0

        actual_candidates = (actual, *self._labeled_answer_candidates(prediction))
        expected_candidates = (expected, *self._labeled_answer_candidates(expected_answer))
        percent_context = self._percent_context(context, expected_answer)
        for actual_candidate in dict.fromkeys(actual_candidates):
            normalized_actual = self._normalize_fallback(actual_candidate)
            for expected_candidate in dict.fromkeys(expected_candidates):
                normalized_expected = self._normalize_fallback(expected_candidate)
                if self._source_equal(normalized_actual, normalized_expected):
                    return 1.0
                if percent_context and self._percent_points_equal(normalized_actual, normalized_expected):
                    return 1.0
        return 0.0


MATHScorer = MATHBenchmark
__all__ = ["MATHBenchmark", "MATHScorer"]
