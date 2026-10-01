"""Convert the final Programmer attempt into OperatorResult."""
from __future__ import annotations
from typing import Any
from masfactory.components.custom_node import CustomNode
from applications.maas_reproduction.maas_reproduction.schemas import OperatorResult


class ProgrammerResultNode(CustomNode):
    def __init__(self, name: str = "ProgrammerResultNode", **kwargs: Any) -> None:
        super().__init__(name, forward=self._forward, pull_keys={}, push_keys={}, **kwargs)

    def _forward(self, data: dict[str, Any]) -> dict[str, Any]:
        success = bool(data.get("execution_success"))
        output = data.get("execution_output")
        return {"operator_result": OperatorResult(
            "Programmer", "success" if success else ("timeout" if "timeout" in str(output).lower() else "failed"),
            solution=output if success else None,
            code=data.get("code"), execution_output=output,
            metadata={"attempts": max(1, int(data.get("attempt", 2)) - 1)},
        )}


__all__ = ["ProgrammerResultNode"]
