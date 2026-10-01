"""Benchmark completion seam: normalize the execution result before scoring."""
from __future__ import annotations
from typing import Any
from masfactory.components.graphs.graph import Graph
from masfactory.components.custom_node import CustomNode

class BenchmarkCompletionGraph(Graph):
    def __init__(self, name: str = "benchmark_completion", *, dataset: str = "GSM8K"):
        super().__init__(name, pull_keys={}, push_keys={})
        self.dataset = dataset

    def build(self) -> None:
        if self._is_built: return
        node = self.create_node(CustomNode, "completion_result", forward=self._complete,
                                pull_keys={}, push_keys={})
        self.edge_from_entry(node, {
            "dispatch_state": "Final dispatch state.",
            "failure_source": "Bootstrap or execution failure source.",
            "error_state": "Structured execution error state.",
        })
        self.edge_to_exit(node, {
            "completion_result": "Normalized completion.",
            "dispatch_state": "Final dispatch state for finalization.",
            "failure_source": "Execution failure source.",
            "error_state": "Structured execution error state.",
        })
        super().build()

    @staticmethod
    def _complete(message: dict[str, Any]) -> dict[str, Any]:
        state = message.get("dispatch_state")
        prediction = getattr(state, "current_solution", None)
        if isinstance(state, dict): prediction = state.get("current_solution", state.get("prediction"))
        return {
            "completion_result": {"prediction": prediction},
            "dispatch_state": state,
            "failure_source": message.get("failure_source"),
            "error_state": message.get("error_state"),
        }

def build_completion_graph(**kwargs: Any) -> BenchmarkCompletionGraph:
    return BenchmarkCompletionGraph(**kwargs)

__all__ = ["BenchmarkCompletionGraph", "build_completion_graph"]
