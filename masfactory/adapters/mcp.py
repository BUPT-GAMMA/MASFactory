from __future__ import annotations

from typing import Any, Callable, Iterable

from masfactory.adapters.context.provider import ContextProvider
from masfactory.adapters.context.types import ContextBlock, ContextQuery


class MCP(ContextProvider):
    """MCP-backed context provider.

    This adapter is intentionally lightweight: it delegates to a user-supplied callable that
    talks to an MCP server/tool and maps returned items into `ContextBlock`.
    """

    supports_passive: bool = True
    supports_active: bool = True

    def __init__(
        self,
        *,
        name: str = "MCP",
        call: Callable[[ContextQuery, int], Iterable[dict[str, Any]]],
        text_key: str = "text",
        uri_key: str = "uri",
        chunk_id_key: str = "chunk_id",
        score_key: str = "score",
        title_key: str = "title",
        metadata_key: str = "metadata",
        dedupe_key_key: str = "dedupe_key",
        passive: bool = True,
        active: bool = False,
    ):
        self._name = name
        self._call = call
        self.passive = passive
        self.active = active
        self._keys = {
            "text": text_key,
            "uri": uri_key,
            "chunk_id": chunk_id_key,
            "score": score_key,
            "title": title_key,
            "metadata": metadata_key,
            "dedupe_key": dedupe_key_key,
        }

    @property
    def context_label(self) -> str:
        return self._name

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        items = list(self._call(query, int(top_k)))
        blocks: list[ContextBlock] = []
        for item in items:
            text = item.get(self._keys["text"])
            if not isinstance(text, str) or not text.strip():
                continue
            blocks.append(
                ContextBlock(
                    text=text,
                    uri=item.get(self._keys["uri"]),
                    chunk_id=item.get(self._keys["chunk_id"]),
                    score=item.get(self._keys["score"]),
                    title=item.get(self._keys["title"]),
                    metadata=item.get(self._keys["metadata"]) or {},
                    dedupe_key=item.get(self._keys["dedupe_key"]),
                )
            )
        return blocks
