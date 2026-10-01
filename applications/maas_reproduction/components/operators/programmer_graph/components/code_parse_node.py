"""Deterministic code validation node."""
from __future__ import annotations
from typing import Any
from masfactory.components.custom_node import CustomNode
from ..programmer_core import ProgrammerCore


class CodeParseNode(CustomNode):
    def __init__(self, name: str = "CodeParseNode", **kwargs: Any) -> None:
        super().__init__(name, forward=self._forward, pull_keys={}, push_keys={}, **kwargs)

    def _forward(self, data: dict[str, Any]) -> dict[str, Any]:
        code = data.get("code")
        error = data.get("generation_error")
        if error:
            return {**data, "parse_error": error}
        try:
            ProgrammerCore.parse(code)
        except ValueError as exc:
            return {**data, "parse_error": str(exc)}
        return {**data, "parse_error": None}


__all__ = ["CodeParseNode"]
