"""Validate and forward the execution-only architecture request."""

from __future__ import annotations

from typing import Any

from masfactory.components.custom_node import CustomNode

from applications.maas_reproduction.maas_reproduction.schemas import ArchitectureRequest


def initialize_execution(message: dict[str, Any]) -> dict[str, object]:
    request = message.get("architecture_request", message.get("request"))
    if not isinstance(request, ArchitectureRequest):
        return {
            "architecture_request": None,
            "failure_source": "infrastructure",
            "error_state": {"stage": "initialize", "message": "invalid ArchitectureRequest"},
        }
    return {"architecture_request": request}


class InitializeExecutionNode(CustomNode):
    def __init__(self, name: str = "initialize_execution", **kwargs: Any) -> None:
        super().__init__(
            name=name,
            forward=initialize_execution,
            pull_keys={},
            push_keys={},
            **kwargs,
        )


__all__ = ["InitializeExecutionNode", "initialize_execution"]
