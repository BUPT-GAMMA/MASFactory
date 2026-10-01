"""Three-sample chain-of-thought operator."""
from __future__ import annotations
from typing import Any
from masfactory.components.custom_node import CustomNode
from masfactory.components.graphs.graph import Graph
from applications.maas_reproduction.maas_reproduction.schemas import OperatorResult
from .native_agent_operator_graph import _call, normalize_result


class MultiGenerateCoTGraph(Graph):
    def __init__(self, name: str = "MultiGenerateCoT", *, operator: Any = None, agent: Any = None,
                 raise_on_error: bool = False) -> None:
        super().__init__(name, pull_keys={}, push_keys={})
        self.adapter = operator if operator is not None else agent
        self.raise_on_error = bool(raise_on_error)

    def build(self) -> None:
        if self._is_built: return
        node = self.create_node(CustomNode, "MultiGenerateCoTNode", forward=self._forward_operator,
                                pull_keys={}, push_keys={})
        self.edge_from_entry(node, {"operator_invocation": "OperatorInvocation or mapping."})
        self.edge_to_exit(node, {"operator_result": "Structured OperatorResult."})
        super().build()

    def _forward_operator(self, data: dict[str, Any]) -> dict[str, Any]:
        invocation = data.get("operator_invocation", data)
        payload = dict(invocation) if isinstance(invocation, dict) else {"operator_invocation": invocation}
        responses: list[str] = []
        try:
            for _ in range(3):
                result = normalize_result(_call(self.adapter, payload), "MultiGenerateCoT")
                if result.solution:
                    responses.append(result.solution)
                elif result.candidates:
                    # Source MaAS performs three independent calls and each
                    # call contributes one response at most.
                    responses.append(result.candidates[0])
            return {"operator_result": OperatorResult("MultiGenerateCoT", "success",
                                                        solution=responses[0] if responses else None,
                                                        candidates=tuple(responses))}
        except Exception as exc:
            if self.raise_on_error:
                raise
            return {"operator_result": OperatorResult("MultiGenerateCoT", "failed",
                                                        candidates=tuple(responses),
                                                        execution_output=str(exc),
                                                        metadata={"error_type": type(exc).__name__})}


MultiGenerateCoT = MultiGenerateCoTGraph

__all__ = ["MultiGenerateCoTGraph", "MultiGenerateCoT"]
