"""Structured handling for operators absent from the registry."""

from __future__ import annotations

from masfactory.components.custom_node import CustomNode

from applications.maas_reproduction.maas_reproduction.schemas import OperatorInvocation, OperatorResult


def invalid_operator_forward(message: dict, attributes: dict) -> dict:
    invocation = message["operator_invocation"]
    if isinstance(invocation, OperatorInvocation):
        name = invocation.operator_name
    else:
        name = invocation["operator_name"]
    return {
        "operator_result": OperatorResult(
            operator_name=name,
            status="invalid_operator",
            metadata={"error": f"operator is not registered: {name}"},
        )
    }


class InvalidOperatorNode(CustomNode):
    def __init__(self, name: str = "invalid_operator") -> None:
        super().__init__(
            name=name,
            forward=invalid_operator_forward,
            pull_keys={},
            push_keys={},
        )


__all__ = ["InvalidOperatorNode", "invalid_operator_forward"]
