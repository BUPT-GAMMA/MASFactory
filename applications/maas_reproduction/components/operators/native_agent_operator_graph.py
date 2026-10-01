"""Shared native graph for the single-shot MaAS operators."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from masfactory.components.custom_node import CustomNode
from masfactory.components.graphs.graph import Graph

from applications.maas_reproduction.maas_reproduction.schemas import OperatorInvocation, OperatorResult


def _call(adapter: Any, payload: dict[str, Any]) -> Any:
    if adapter is None:
        raise RuntimeError("operator adapter is not configured")
    if hasattr(adapter, "invoke"):
        value = adapter.invoke(payload)
        return value[0] if isinstance(value, tuple) else value
    if callable(adapter):
        return adapter(payload)
    raise TypeError("operator adapter must expose invoke() or be callable")


def normalize_result(value: Any, operator_name: str, *, default_status: str = "success") -> OperatorResult:
    """Convert an adapter response into the canonical operator result."""
    if isinstance(value, OperatorResult):
        return value
    if isinstance(value, Mapping):
        data: Any = value.get("operator_result", value)
        if isinstance(data, OperatorResult):
            return data
        if not isinstance(data, Mapping):
            raise TypeError("operator_result must be a mapping")
        data = dict(data)
        data.setdefault("operator_name", operator_name)
        data.setdefault("status", default_status)
        if "response" in data and "solution" not in data:
            data["solution"] = data.pop("response")
        allowed = {"operator_name", "status", "solution", "candidates", "code",
                   "execution_output", "metadata"}
        return OperatorResult(**{key: data[key] for key in allowed if key in data})
    if isinstance(value, str):
        return OperatorResult(operator_name, default_status, solution=value)
    raise TypeError(f"{operator_name} returned an unsupported response")


class NativeAgentOperatorGraph(Graph):
    """Deep module shared by Generate, GenerateCoT, and SelfRefine."""

    def __init__(self, name: str = "NativeAgentOperatorGraph", *, operator_name: str = "Generate",
                 operator: Any = None, agent: Any = None, instructions: str = "",
                 retry_limit: int = 0, validator: Callable[[OperatorResult], None] | None = None,
                 raise_on_error: bool = False) -> None:
        # This operator graph is embedded below the protected architecture
        # subtree.  It must never inherit caller attributes implicitly.
        super().__init__(name, pull_keys={}, push_keys={})
        if retry_limit < 0 or isinstance(retry_limit, bool):
            raise ValueError("retry_limit must be a non-negative integer")
        self.operator_name, self.adapter = operator_name, operator if operator is not None else agent
        self.instructions, self.retry_limit, self.validator = instructions, retry_limit, validator
        self.raise_on_error = bool(raise_on_error)

    def build(self) -> None:
        if self._is_built:
            return
        node = self.create_node(CustomNode, "NativeAgentNode", forward=self._forward_operator,
                                pull_keys={}, push_keys={})
        self.edge_from_entry(node, {"operator_invocation": "OperatorInvocation or mapping."})
        self.edge_to_exit(node, {"operator_result": "Structured OperatorResult."})
        super().build()

    def _forward_operator(self, data: dict[str, Any]) -> dict[str, Any]:
        invocation = data.get("operator_invocation", data)
        # Accept the canonical dataclass and equivalent objects imported via
        # the fully-qualified ``applications.maas_reproduction`` path.  The
        # latter can be a distinct Python class during test collection; the
        # contract is structural, so do not turn that import detail into an
        # execution failure.
        if isinstance(invocation, OperatorInvocation) or all(
            hasattr(invocation, field)
            for field in ("operator_name", "problem", "entry_point", "current_solution", "candidates")
        ):
            payload = {"operator_invocation": invocation, "problem": invocation.problem,
                       "entry_point": invocation.entry_point, "current_solution": invocation.current_solution,
                       "candidates": invocation.candidates, "instructions": self.instructions}
        elif isinstance(invocation, Mapping):
            payload = {**invocation, "instructions": self.instructions}
        else:
            return {"operator_result": OperatorResult(self.operator_name, "invalid_input",
                                                        metadata={"error": "invalid operator_invocation"})}
        error: Exception | None = None
        for _ in range(self.retry_limit + 1):
            try:
                result = normalize_result(_call(self.adapter, payload), self.operator_name)
                if self.validator:
                    self.validator(result)
                return {"operator_result": result}
            except Exception as exc:  # recover adapter/validation failures at the seam
                error = exc
        if self.raise_on_error and error is not None:
            raise error
        return {"operator_result": OperatorResult(self.operator_name, "failed",
                                                    execution_output=str(error),
                                                    metadata={"error_type": type(error).__name__})}


class GenerateGraph(NativeAgentOperatorGraph):
    def __init__(self, name: str = "Generate", **kwargs: Any) -> None:
        super().__init__(name, operator_name="Generate", **kwargs)


class GenerateCoTGraph(NativeAgentOperatorGraph):
    def __init__(self, name: str = "GenerateCoT", **kwargs: Any) -> None:
        super().__init__(name, operator_name="GenerateCoT", **kwargs)


class SelfRefineGraph(NativeAgentOperatorGraph):
    def __init__(self, name: str = "SelfRefine", **kwargs: Any) -> None:
        super().__init__(name, operator_name="SelfRefine", **kwargs)


Generate = GenerateGraph
GenerateCoT = GenerateCoTGraph
SelfRefine = SelfRefineGraph

__all__ = ["NativeAgentOperatorGraph", "GenerateGraph", "GenerateCoTGraph", "SelfRefineGraph",
           "Generate", "GenerateCoT", "SelfRefine", "normalize_result"]
