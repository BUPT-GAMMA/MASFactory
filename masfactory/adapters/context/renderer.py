from __future__ import annotations

from abc import ABC, abstractmethod

from .policy import ProviderBlocks


class ContextRenderer(ABC):
    """Renderer that injects selected context into a user prompt payload."""

    @abstractmethod
    def inject(self, user_payload: dict, provider_blocks: list[ProviderBlocks]) -> dict:
        """Return a new user payload with context injected."""
        raise NotImplementedError


class DefaultContextRenderer(ContextRenderer):
    """Inject context as a single `CONTEXT` field in the user payload."""

    def __init__(self, *, key: str = "CONTEXT"):
        self._key = key

    def inject(self, user_payload: dict, provider_blocks: list[ProviderBlocks]) -> dict:
        if not provider_blocks:
            return user_payload

        rendered = self._render(provider_blocks)
        if not rendered:
            return user_payload

        merged = dict(user_payload)
        merged[self._key] = rendered
        return merged

    def _render(self, provider_blocks: list[ProviderBlocks]) -> str:
        lines: list[str] = ["[Context]"]
        for provider_label, blocks in provider_blocks:
            for block in blocks:
                lines.append(f"({provider_label}) {block.text}".rstrip())
        return "\n".join(lines).strip()

