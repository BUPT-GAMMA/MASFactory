"""Source-compatible HumanEval public testing and XML parsing."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable

from ..adapters.code_executor import CodeExecutor


_HARDCODED_EMPTY_CASES = frozenset(
    {
        "find_zero",
        "decode_cyclic",
        "decode_shift",
        "by_length",
        "add",
        "triangle_area",
        "correct_bracketing",
        "solve",
        "sum_squares",
        "starts_one_ends",
    }
)


@dataclass(frozen=True, slots=True)
class PublicTestResult:
    passed: bool
    feedback: str
    failed_cases: tuple[str, ...] = ()
    execution_succeeded: bool = True


class HumanEvalPublicTestRepository:
    """Load the source public-test cases without exposing hidden evaluator data."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._cases: dict[str, tuple[str, ...]] | None = None

    @staticmethod
    def _normalize(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            # Preserve the source loop's behavior for string-valued fixtures.
            return tuple(value)
        if isinstance(value, Iterable):
            return tuple(str(item) for item in value)
        raise TypeError("HumanEval public tests must be a string, iterable, or null")

    def _load(self) -> dict[str, tuple[str, ...]]:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        cases: dict[str, tuple[str, ...]] = {}
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                entrypoint = row.get("entry_point")
                if not isinstance(entrypoint, str) or not entrypoint:
                    raise ValueError(f"missing entry_point at {self.path}:{line_number}")
                cases[entrypoint] = self._normalize(row.get("test"))
        return cases

    def get(self, entry_point: str) -> tuple[str, ...]:
        if entry_point in _HARDCODED_EMPTY_CASES:
            return ()
        if self._cases is None:
            self._cases = self._load()
        return self._cases.get(entry_point, ())


def _public_test_source(solution: str, test_case: str, entry_point: str) -> str:
    return f"""
{solution}

def check(candidate):
    {test_case}

def test_check():
    check({entry_point})

test_check()
"""


class SourceHumanEvalExecutor:
    """Execute public tests with source semantics inside bounded subprocesses."""

    def __init__(self, *, executor: CodeExecutor | None = None, timeout_seconds: float = 15.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.executor = executor or CodeExecutor(max_output_chars=10000)
        self.timeout_seconds = float(timeout_seconds)

    def run_public_tests(
        self,
        solution: str,
        test_cases: Iterable[str],
        entry_point: str,
    ) -> PublicTestResult:
        failures: list[str] = []
        for test_case in test_cases:
            result = self.executor.execute(
                _public_test_source(str(solution), str(test_case), entry_point),
                timeout_seconds=self.timeout_seconds,
            )
            if result.success:
                continue
            detail = "Execution timed out" if result.timed_out else (
                result.stderr.strip() or result.error or "execution failed"
            )
            failures.append(f"{test_case}: {detail}")
            # Source Test returns immediately for non-assertion execution
            # failures.  A subprocess does not expose exception classes, so a
            # syntax/runtime traceback is sufficient feedback for reflection.
            if "AssertionError" not in detail:
                return PublicTestResult(
                    False,
                    detail,
                    tuple(failures),
                    execution_succeeded=False,
                )
        if failures:
            return PublicTestResult(
                False,
                "\n".join(failures),
                tuple(failures),
                execution_succeeded=True,
            )
        return PublicTestResult(True, "no error")


_SOLUTION_LETTER = re.compile(
    r"<solution_letter>\s*([A-Za-z])\s*</solution_letter>", re.DOTALL
)


class RecoverableModelOutputError(ValueError):
    """A model response violated a source output contract after retries."""


def compile_sc_ensemble_xml_prompt(context: str) -> str:
    """Reproduce ``ActionNode.xml_compile`` for ``ScEnsembleOp``.

    Field order is source-significant because the legacy Pydantic operation
    declares ``thought`` before ``solution_letter``.
    """
    return str(context) + """
### Response format (must be strictly followed): All content must be enclosed in the given XML tags, ensuring each opening <tag> has a corresponding closing </tag>, with no incomplete or self-closing tags allowed.

<thought>content</thought>
<solution_letter>content</solution_letter>
"""


def parse_solution_letter_xml(text: str, candidate_count: int) -> str:
    """Parse exactly the XML field required by source ``xml_fill``."""
    match = _SOLUTION_LETTER.search(str(text))
    if match is None:
        raise RecoverableModelOutputError("ScEnsemble response lacks <solution_letter>")
    letter = match.group(1).upper()
    index = ord(letter) - ord("A")
    if not 0 <= index < candidate_count:
        raise RecoverableModelOutputError("ScEnsemble solution_letter is out of range")
    return letter


__all__ = [
    "HumanEvalPublicTestRepository",
    "PublicTestResult",
    "SourceHumanEvalExecutor",
    "RecoverableModelOutputError",
    "compile_sc_ensemble_xml_prompt",
    "parse_solution_letter_xml",
]
