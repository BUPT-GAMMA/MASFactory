"""Injected execution adapter node."""
from __future__ import annotations
from typing import Any
from masfactory.components.custom_node import CustomNode
from ..programmer_core import ProgrammerCore


class ProgrammerExecutionNode(CustomNode):
    def __init__(self, name: str = "ProgrammerExecutionNode", *, executor: Any = None, **kwargs: Any) -> None:
        self.executor = executor
        super().__init__(name, forward=self._forward, pull_keys={}, push_keys={}, **kwargs)

    def _forward(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("parse_error"):
            return {**data, "execution_success": False, "execution_output": data["parse_error"],
                    "feedback": data["parse_error"]}
        try:
            success, text, error = ProgrammerCore(generator=None, executor=self.executor).execute(data, data.get("code", ""))
            if not success:
                return {**data, "execution_success": False, "execution_output": text, "feedback": error}
            return {**data, "execution_success": True, "execution_output": text, "feedback": ""}
        except Exception as exc:
            return {**data, "execution_success": False, "execution_output": str(exc), "feedback": str(exc)}


__all__ = ["ProgrammerExecutionNode"]
