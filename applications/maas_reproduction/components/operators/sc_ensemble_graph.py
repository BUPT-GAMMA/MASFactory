"""Self-consistency ensemble operator."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from masfactory.components.custom_node import CustomNode
from masfactory.components.graphs.graph import Graph
from applications.maas_reproduction.maas_reproduction.schemas import OperatorResult
from .native_agent_operator_graph import _call


class ScEnsembleGraph(Graph):
    def __init__(self, name: str = "ScEnsemble", *, operator: Any = None, agent: Any = None,
                 raise_on_error: bool = False) -> None:
        super().__init__(name, pull_keys={}, push_keys={}); self.adapter = operator if operator is not None else agent
        self.raise_on_error = bool(raise_on_error)

    def build(self) -> None:
        if self._is_built: return
        node = self.create_node(CustomNode, "ScEnsembleNode", forward=self._forward_operator,
                                pull_keys={}, push_keys={})
        self.edge_from_entry(node, {"operator_invocation": "OperatorInvocation or mapping."})
        self.edge_to_exit(node, {"operator_result": "Structured OperatorResult."})
        super().build()

    def _forward_operator(self, data: dict[str, Any]) -> dict[str, Any]:
        invocation = data.get("operator_invocation", data)
        candidates = tuple(invocation.candidates) if hasattr(invocation, "candidates") else tuple(invocation.get("candidates", ()))
        if not candidates:
            error = ValueError("ScEnsemble requires at least one candidate")
            return {"operator_result": OperatorResult(
                "ScEnsemble", "failed", execution_output=str(error),
                metadata={"error_type": type(error).__name__, "error": str(error)},
            )}
        try:
            answer = _call(self.adapter, {"solutions": {chr(65+i): value for i, value in enumerate(candidates)},
                                          "candidates": candidates, "problem": getattr(invocation, "problem", "")})
            letter = answer.get("solution_letter") if isinstance(answer, Mapping) else getattr(answer, "solution_letter", answer)
            index = ord(str(letter).strip().upper()) - 65
            if not 0 <= index < len(candidates):
                raise ValueError("invalid solution_letter")
            return {"operator_result": OperatorResult("ScEnsemble", "success", solution=candidates[index], candidates=candidates)}
        except Exception as exc:
            if self.raise_on_error:
                raise
            return {"operator_result": OperatorResult(
                "ScEnsemble", "failed", candidates=candidates,
                execution_output=str(exc),
                metadata={"error_type": type(exc).__name__, "error": str(exc)},
            )}


ScEnsemble = ScEnsembleGraph

__all__ = ["ScEnsembleGraph", "ScEnsemble"]
