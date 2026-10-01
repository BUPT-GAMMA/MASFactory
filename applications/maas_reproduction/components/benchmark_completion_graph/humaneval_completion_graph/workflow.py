"""Source-compatible fixed HumanEval Test and fallback completion."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from masfactory.components.custom_node import CustomNode
from masfactory.components.graphs.graph import Graph

from applications.maas_reproduction.maas_reproduction.schemas import DispatchState
from applications.maas_reproduction.components.operators.humaneval_test_graph import HumanEvalTestProtocol


def _call(adapter: Any, payload: dict[str, Any]) -> Any:
    if adapter is None:
        raise RuntimeError("HumanEval fallback adapter is not configured")
    if hasattr(adapter, "invoke"):
        value = adapter.invoke(payload)
        return value[0] if isinstance(value, tuple) else value
    if callable(adapter):
        return adapter(payload)
    raise TypeError("HumanEval fallback adapter must be callable or expose invoke()")


def _solution(value: Any) -> str:
    if isinstance(value, str):
        result = value
    elif isinstance(value, Mapping):
        result = value.get("solution", value.get("response", ""))
    else:
        result = getattr(value, "solution", "")
    if not isinstance(result, str):
        raise TypeError("HumanEval fallback solution must be source text")
    return result


class HumanEvalCompletionGraph(Graph):
    def __init__(
        self,
        name: str = "humaneval_completion",
        *,
        protocol: HumanEvalTestProtocol | None = None,
        fallback_adapter: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, pull_keys={}, push_keys={}, **kwargs)
        self.protocol = protocol
        self.fallback_adapter = fallback_adapter

    def build(self) -> None:
        if self._is_built:
            return
        node = self.create_node(
            CustomNode,
            "HumanEvalCompletionNode",
            forward=self._complete,
            pull_keys={},
            push_keys={},
        )
        self.edge_from_entry(node, {
            "dispatch_state": "Final HumanEval dispatch state.",
            "failure_source": "Upstream failure source.",
            "error_state": "Upstream structured error state.",
        })
        self.edge_to_exit(node, {
            "completion_result": "Source-compatible HumanEval completion.",
            "dispatch_state": "Final dispatch state.",
            "failure_source": "Execution failure source.",
            "error_state": "Structured execution error state.",
        })
        super().build()

    def _complete(self, message: dict[str, Any]) -> dict[str, Any]:
        if self.protocol is None:
            raise RuntimeError("HumanEval completion Test protocol is not configured")
        state = message.get("dispatch_state")
        if not isinstance(state, DispatchState):
            return {
                "completion_result": {"prediction": None, "status": "invalid_result"},
                "dispatch_state": state,
                "failure_source": message.get("failure_source"),
                "error_state": message.get("error_state"),
            }
        initial = state.current_solution or (state.candidates[-1] if state.candidates else "")
        outcome = self.protocol.run(
            problem=state.request.problem,
            entry_point=state.request.entry_point,
            solution=initial,
        )
        fallback_used = False
        prediction = outcome.solution
        if not outcome.passed:
            fallback_used = True
            prediction = _solution(
                _call(
                    self.fallback_adapter,
                    {
                        "problem": state.request.problem,
                        "entry_point": state.request.entry_point,
                        "current_solution": outcome.solution,
                        "public_test_feedback": outcome.feedback,
                    },
                )
            )
        return {
            "completion_result": {
                "prediction": prediction,
                "status": "completed",
                "metadata": {
                    "fixed_public_test_passed": outcome.passed,
                    "fixed_test_repair_attempts": outcome.repair_attempts,
                    "fixed_public_test_runs": outcome.public_test_runs,
                    "fallback_used": fallback_used,
                    "execution_timeout_policy": "process_wide_15s",
                },
            },
            "dispatch_state": state,
            "failure_source": message.get("failure_source"),
            "error_state": message.get("error_state"),
        }


__all__ = ["HumanEvalCompletionGraph"]
