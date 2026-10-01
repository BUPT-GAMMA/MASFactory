"""Source-compatible HumanEval public-test and repair protocol."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from masfactory.components.custom_node import CustomNode
from masfactory.components.graphs.graph import Graph

from applications.maas_reproduction.maas_reproduction.schemas import OperatorInvocation, OperatorResult
from applications.maas_reproduction.maas_reproduction.source_compat import (
    HumanEvalPublicTestRepository,
    SourceHumanEvalExecutor,
)


def _call(adapter: Any, payload: dict[str, Any]) -> Any:
    if adapter is None:
        raise RuntimeError("HumanEval reflection adapter is not configured")
    if hasattr(adapter, "invoke"):
        value = adapter.invoke(payload)
        return value[0] if isinstance(value, tuple) else value
    if callable(adapter):
        return adapter(payload)
    raise TypeError("HumanEval reflection adapter must be callable or expose invoke()")


def _solution(value: Any) -> str:
    if isinstance(value, str):
        result = value
    elif isinstance(value, Mapping):
        result = value.get(
            "reflection_and_solution",
            value.get("solution", value.get("response", "")),
        )
    else:
        result = getattr(value, "reflection_and_solution", getattr(value, "solution", ""))
    if not isinstance(result, str):
        raise TypeError("HumanEval reflection must return source text")
    return result


@dataclass(frozen=True, slots=True)
class HumanEvalTestOutcome:
    solution: str
    passed: bool
    feedback: str
    repair_attempts: int
    public_test_runs: int


class HumanEvalTestProtocol:
    """Deep module shared by route Test and fixed benchmark completion."""

    def __init__(
        self,
        *,
        repository: HumanEvalPublicTestRepository,
        executor: SourceHumanEvalExecutor,
        reflection_adapter: Any,
        max_repairs: int = 3,
    ) -> None:
        if isinstance(max_repairs, bool) or not isinstance(max_repairs, int) or max_repairs < 0:
            raise ValueError("max_repairs must be a non-negative integer")
        self.repository = repository
        self.executor = executor
        self.reflection_adapter = reflection_adapter
        self.max_repairs = max_repairs

    def run(self, *, problem: str, entry_point: str, solution: str) -> HumanEvalTestOutcome:
        cases = self.repository.get(entry_point)
        current = str(solution)
        test_runs = 0
        feedback = ""
        for attempt in range(self.max_repairs):
            result = self.executor.run_public_tests(current, cases, entry_point)
            test_runs += 1
            feedback = result.feedback
            if result.passed:
                return HumanEvalTestOutcome(current, True, feedback, attempt, test_runs)
            reflected = _call(
                self.reflection_adapter,
                {
                    "problem": problem,
                    "entry_point": entry_point,
                    "solution": current,
                    "exec_pass": (
                        "executed successfully"
                        if result.execution_succeeded
                        else f"executed unsuccessfully, error: \n {result.feedback}"
                    ),
                    "test_fail": (
                        result.feedback
                        if result.execution_succeeded
                        else "executed unsucessfully"
                    ),
                },
            )
            current = _solution(reflected)

        final = self.executor.run_public_tests(current, cases, entry_point)
        test_runs += 1
        return HumanEvalTestOutcome(
            current,
            final.passed,
            final.feedback,
            self.max_repairs,
            test_runs,
        )


class HumanEvalTestGraph(Graph):
    """Expose the shared protocol as an OperatorInvocation -> OperatorResult graph."""

    def __init__(self, name: str = "Test", *, protocol: HumanEvalTestProtocol | None = None) -> None:
        super().__init__(name, pull_keys={}, push_keys={})
        self.protocol = protocol

    def build(self) -> None:
        if self._is_built:
            return
        node = self.create_node(
            CustomNode,
            "HumanEvalTestNode",
            forward=self._forward_test,
            pull_keys={},
            push_keys={},
        )
        self.edge_from_entry(node, {"operator_invocation": "HumanEval Test invocation."})
        self.edge_to_exit(node, {"operator_result": "Completed HumanEval public-test protocol."})
        super().build()

    def _forward_test(self, message: dict[str, Any]) -> dict[str, Any]:
        if self.protocol is None:
            raise RuntimeError("HumanEval Test protocol is not configured")
        invocation = message.get("operator_invocation", message)
        if isinstance(invocation, OperatorInvocation) or all(
            hasattr(invocation, field) for field in ("problem", "entry_point", "current_solution")
        ):
            problem = invocation.problem
            entry_point = invocation.entry_point
            solution = invocation.current_solution
        elif isinstance(invocation, Mapping):
            problem = str(invocation.get("problem", ""))
            entry_point = str(invocation.get("entry_point", ""))
            solution = str(invocation.get("current_solution", invocation.get("solution", "")))
        else:
            raise TypeError("HumanEval Test requires an OperatorInvocation")
        outcome = self.protocol.run(problem=problem, entry_point=entry_point, solution=solution)
        return {
            "operator_result": OperatorResult(
                operator_name="Test",
                status="completed",
                solution=outcome.solution,
                execution_output=outcome.feedback,
                metadata={
                    "public_test_passed": outcome.passed,
                    "repair_attempts": outcome.repair_attempts,
                    "public_test_runs": outcome.public_test_runs,
                },
            )
        }


__all__ = [
    "HumanEvalTestGraph",
    "HumanEvalTestOutcome",
    "HumanEvalTestProtocol",
]
