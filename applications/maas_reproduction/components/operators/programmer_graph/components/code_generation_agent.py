"""Code-generation node for the native Programmer operator."""
from __future__ import annotations
from typing import Any
from masfactory.components.custom_node import CustomNode
from ..workflow_helpers import call_adapter
from ..programmer_core import ProgrammerCore


class CodeGenerationAgent(CustomNode):
    def __init__(self, name: str = "CodeGenerationAgent", *, generator: Any = None, **kwargs: Any) -> None:
        self.generator = generator
        super().__init__(name, forward=self._forward, pull_keys={}, push_keys={}, **kwargs)

    def _forward(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            attempt = data.get("attempt", 1)
            if not isinstance(attempt, int) or isinstance(attempt, bool):
                attempt = 1
            feedback = data.get("feedback", "")
            if not isinstance(feedback, str) or feedback == "(not set yet)":
                feedback = ""
            generated = call_adapter(self.generator, {
                **data, "feedback": feedback, "attempt": attempt,
            })
            code = ProgrammerCore.parse(generated)
            return {**data, "attempt": attempt, "code": code, "generation_error": None}
        except Exception as exc:  # preserve the retry seam
            return {**data, "attempt": attempt if "attempt" in locals() else 1,
                    "code": None, "generation_error": str(exc)}


__all__ = ["CodeGenerationAgent"]
