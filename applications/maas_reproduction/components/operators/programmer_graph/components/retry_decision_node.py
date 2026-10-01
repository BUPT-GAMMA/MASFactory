"""Retry decision node; it has no external side effects."""
from __future__ import annotations
from typing import Any
from masfactory.components.custom_node import CustomNode


class RetryDecisionNode(CustomNode):
    def __init__(self, name: str = "RetryDecisionNode", *, max_attempts: int = 3, **kwargs: Any) -> None:
        self.max_attempts = max_attempts
        super().__init__(name, forward=self._forward, pull_keys={}, push_keys={}, **kwargs)

    def _forward(self, data: dict[str, Any]) -> dict[str, Any]:
        attempt = int(data.get("attempt", 1))
        retry = not data.get("execution_success", False) and attempt < self.max_attempts
        return {**data, "retry_requested": retry, "attempt": attempt + 1}


__all__ = ["RetryDecisionNode"]
