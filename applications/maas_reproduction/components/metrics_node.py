from __future__ import annotations
from typing import Any
from masfactory.components.custom_node import CustomNode


class MetricsNode(CustomNode):
    """Record test metrics without mutating training state."""
    def __init__(self, name: str = "metrics", metrics: object | None = None, **kwargs: Any) -> None:
        self.metrics = metrics
        super().__init__(name=name, forward=self._record, **kwargs)

    def _record(self, message: dict[str, object]) -> dict[str, object]:
        evaluation = message.get("evaluation_result")
        if self.metrics is not None and hasattr(self.metrics, "record"):
            self.metrics.record(evaluation)
        return {"evaluation_result": evaluation}


__all__ = ["MetricsNode"]
