"""HumanEval scorer with source-compatible helpers and bounded execution."""
from __future__ import annotations

import base64
from typing import Any

from ..adapters.code_executor import CodeExecutor
from ..source_compat.sanitize import sanitize as _sanitize
from .base import BaseBenchmark, ScoreResult


_EXECUTION_TIMEOUT_SECONDS = 15.0
_PASS_MARKER = "__MAAS_HUMANEVAL_PASS__"
_FAIL_MARKER = "__MAAS_HUMANEVAL_FAIL__"
def _special_helpers(entrypoint: str) -> str:
    if entrypoint == "decode_cyclic":
        return """
def encode_cyclic(s: str):
    groups = [s[(3 * i):min((3 * i + 3), len(s))] for i in range((len(s) + 2) // 3)]
    groups = [(group[1:] + group[0]) if len(group) == 3 else group for group in groups]
    return "".join(groups)
"""
    if entrypoint == "decode_shift":
        return """
def encode_shift(s: str):
    return "".join([chr(((ord(ch) + 5 - ord("a")) % 26) + ord("a")) for ch in s])
"""
    if entrypoint == "find_zero":
        return """
def poly(xs: list, x: float):
    return sum(coeff * (x ** i) for i, coeff in enumerate(xs))
"""
    return ""


def _runner_source(solution: str, test: str, entrypoint: str) -> str:
    encoded_solution = base64.b64encode(solution.encode("utf-8")).decode("ascii")
    encoded_test = base64.b64encode(test.encode("utf-8")).decode("ascii")
    encoded_entrypoint = base64.b64encode(entrypoint.encode("utf-8")).decode("ascii")
    return f"""
import base64
import hashlib
import math
import re
import typing
namespace = {{
    '__name__': '__main__',
    'math': math, 'hashlib': hashlib, 're': re,
    'List': typing.List, 'Dict': typing.Dict, 'Tuple': typing.Tuple,
    'Optional': typing.Optional, 'Any': typing.Any,
}}
solution = base64.b64decode({encoded_solution!r}).decode('utf-8')
test = base64.b64decode({encoded_test!r}).decode('utf-8')
entrypoint = base64.b64decode({encoded_entrypoint!r}).decode('utf-8')
exec(solution, namespace)
if entrypoint not in namespace or not callable(namespace[entrypoint]):
    raise ValueError('entrypoint is not defined')
exec(test, namespace)
check = namespace.get('check')
if not callable(check):
    raise ValueError('test must define check')
result = check(namespace[entrypoint])
print({_PASS_MARKER!r} if result is None else {_FAIL_MARKER!r})
"""


class HumanEvalBenchmark(BaseBenchmark):
    """Execute HumanEval candidates in an isolated, bounded subprocess."""

    PASS = "PASS"
    FAIL = "FAIL"

    def __init__(self, *args: Any, timeout_seconds: float = _EXECUTION_TIMEOUT_SECONDS,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = float(timeout_seconds)
        self._executor = CodeExecutor(max_output_chars=10000)

    def check_solution(self, solution: str | None, test: str, entry_point: str) -> tuple[str, str]:
        try:
            sanitized = _sanitize(str(solution or ""), entry_point)
            code = _special_helpers(entry_point) + "\n" + sanitized
            result = self._executor.execute(
                _runner_source(code, str(test), entry_point),
                timeout_seconds=self.timeout_seconds,
            )
            if result.timed_out:
                return self.FAIL, "Execution timed out."
            if not result.success:
                detail = result.stderr.strip() or result.error or "execution failed"
                return self.FAIL, f"Error: {detail}"
            if _PASS_MARKER in result.stdout:
                return self.PASS, "The solution passed all test cases."
            return self.FAIL, "The solution failed one or more test cases."
        except Exception as exc:
            return self.FAIL, f"Error: {type(exc).__name__}: {exc}"

    def evaluate(self, prediction: str | None, expected_answer: Any, *,
                 context: dict[str, Any] | None = None) -> ScoreResult:
        # The original benchmark treats an empty/invalid candidate as a failed
        # sample with score 0. Keep it trainable instead of making it an
        # evaluator-infrastructure failure.
        if prediction is None or not str(prediction).strip():
            return ScoreResult(0.0, True)
        return super().evaluate(prediction, expected_answer, context=context)

    def score(self, prediction: str | None, expected_answer: Any, *,
              context: dict[str, Any] | None = None) -> float:
        if context is None or not context.get("entry_point") or not context.get("test"):
            raise ValueError("HumanEval requires entry_point and test context")
        status, _ = self.check_solution(
            prediction, str(context["test"]), str(context["entry_point"])
        )
        return 1.0 if status == self.PASS else 0.0


HumanEvalScorer = HumanEvalBenchmark
__all__ = ["HumanEvalBenchmark", "HumanEvalScorer"]
