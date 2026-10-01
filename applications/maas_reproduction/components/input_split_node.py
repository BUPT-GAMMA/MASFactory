from __future__ import annotations

from typing import Any

from masfactory.components.custom_node import CustomNode
from applications.maas_reproduction.maas_reproduction.schemas import ArchitectureRequest, EvaluationContext


class InputSplitNode(CustomNode):
    """Split one dataset envelope into execution and evaluation contexts."""

    def __init__(self, name: str = "input_split", **kwargs: Any) -> None:
        super().__init__(name=name, forward=self._split, pull_keys={}, push_keys={}, **kwargs)

    @staticmethod
    def _split(message: dict[str, Any]) -> dict[str, object]:
        payload = message.get("sample", message)
        if not isinstance(payload, dict):
            raise TypeError("sample input must be a mapping")
        problem = payload.get("problem", payload.get("question"))
        if problem is None:
            raise ValueError("sample is missing problem")
        index = payload.get("problem_index", payload.get("index", 0))
        entry = payload.get("entry_point", "")
        expected = payload.get("expected_answer", payload.get("answer"))
        request = ArchitectureRequest(str(problem), int(index), str(entry))
        context = EvaluationContext(str(problem), int(index), expected, str(entry),
                                    payload.get("test"), payload.get("canonical_solution"))
        return {"architecture_request": request, "evaluation_context": context}


__all__ = ["InputSplitNode"]
