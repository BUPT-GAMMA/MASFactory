from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib

from .types import ContextBlock

ProviderBlocks = tuple[str, list[ContextBlock]]


class ContextPolicy(ABC):
    """Policy that selects/deduplicates/ranks blocks across providers."""

    @abstractmethod
    def select(self, provider_blocks: list[ProviderBlocks], *, top_k: int) -> list[ProviderBlocks]:
        """Return selected blocks grouped by provider (provider order preserved)."""
        raise NotImplementedError


class DefaultContextPolicy(ContextPolicy):
    """Default policy: provider order dominates; score sorts only within provider."""

    def select(self, provider_blocks: list[ProviderBlocks], *, top_k: int) -> list[ProviderBlocks]:
        selected: list[ProviderBlocks] = []
        seen: set[str] = set()
        remaining = max(0, int(top_k))

        for provider_label, blocks in provider_blocks:
            if remaining == 0:
                break

            # Stable sort: score desc; keep score=None in original order (at end).
            scored: list[tuple[int, ContextBlock]] = list(enumerate(blocks))
            scored.sort(
                key=lambda item: (
                    item[1].score is None,
                    -(item[1].score or 0.0),
                    item[0],
                )
            )

            kept: list[ContextBlock] = []
            for _, block in scored:
                if remaining == 0:
                    break

                identity = self._dedupe_identity(block)
                if identity in seen:
                    continue
                seen.add(identity)
                kept.append(block)
                remaining -= 1

            if kept:
                selected.append((provider_label, kept))

        return selected

    def _dedupe_identity(self, block: ContextBlock) -> str:
        if block.dedupe_key:
            return f"dedupe:{block.dedupe_key}"
        if block.uri and block.chunk_id:
            return f"uri_chunk:{block.uri}#{block.chunk_id}"
        if block.uri:
            return f"uri:{block.uri}"
        digest = hashlib.sha1(block.text.encode("utf-8", errors="replace")).hexdigest()
        return f"text_sha1:{digest}"
