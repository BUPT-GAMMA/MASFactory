"""Deterministic offline Model adapter."""
from __future__ import annotations
from masfactory.adapters.model.base import Model

class FakeModel(Model):
    def __init__(self, response: str = "42", responses: dict[str, str] | None = None):
        super().__init__(model_name="fake", invoke_settings={"temperature": 0.0})
        self.response, self.responses, self.messages = response, dict(responses or {}), []
    def invoke(self, messages, tools=None, settings=None, **kwargs):
        self.messages.append(messages)
        text = "\n".join(str(m.get("content", "")) for m in messages)
        value = next((v for key, v in self.responses.items() if key in text), self.response)
        return {"type": "content", "content": value, "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

__all__ = ["FakeModel"]
