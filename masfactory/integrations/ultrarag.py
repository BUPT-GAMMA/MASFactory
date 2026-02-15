from __future__ import annotations

from typing import Any, Callable, Iterable

from masfactory.adapters.context.types import ContextBlock, ContextQuery
from masfactory.adapters.mcp import MCP
from masfactory.adapters.retrieval import Retrieval


class UltraRAGRetriever(Retrieval):
    """UltraRAG integration via a native (in-process) retrieval wrapper.

    This adapter does not depend on the UltraRAG Python package. Instead, you inject a
    callable that talks to UltraRAG and returns iterable items, which are mapped into
    `ContextBlock`.

    Recommended item shape:
    - `text`: str (required)
    - `uri`: str (optional)
    - `chunk_id`: str (optional)
    - `score`: float (optional)
    - `title`: str (optional)
    - `metadata`: dict (optional)
    - `dedupe_key`: str (optional)
    """

    def __init__(
        self,
        *,
        retrieve: Callable[[ContextQuery, int], Iterable[dict[str, Any]]],
        name: str = "UltraRAG",
        text_key: str = "text",
        uri_key: str = "uri",
        chunk_id_key: str = "chunk_id",
        score_key: str = "score",
        title_key: str = "title",
        metadata_key: str = "metadata",
        dedupe_key_key: str = "dedupe_key",
        passive: bool = True,
        active: bool = False,
        supports_passive: bool = True,
        supports_active: bool = True,
    ):
        super().__init__(name, passive=passive, active=active)
        self.supports_passive = bool(supports_passive)
        self.supports_active = bool(supports_active)
        self._retrieve = retrieve
        self._keys = {
            "text": text_key,
            "uri": uri_key,
            "chunk_id": chunk_id_key,
            "score": score_key,
            "title": title_key,
            "metadata": metadata_key,
            "dedupe_key": dedupe_key_key,
        }

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        items = list(self._retrieve(query, int(top_k)))
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


def make_ultrarag_mcp(
    *,
    call: Callable[[ContextQuery, int], Iterable[dict[str, Any]]],
    name: str = "UltraRAG",
    passive: bool = True,
    active: bool = False,
    text_key: str = "text",
    uri_key: str = "uri",
    chunk_id_key: str = "chunk_id",
    score_key: str = "score",
    title_key: str = "title",
    metadata_key: str = "metadata",
    dedupe_key_key: str = "dedupe_key",
) -> MCP:
    """UltraRAG integration via MCP transport.

    Use this when UltraRAG runs out-of-process and you access it through an MCP tool/server.
    The `call(...)` signature matches MASFactory's MCP adapter contract.
    """
    return MCP(
        name=name,
        call=call,
        text_key=text_key,
        uri_key=uri_key,
        chunk_id_key=chunk_id_key,
        score_key=score_key,
        title_key=title_key,
        metadata_key=metadata_key,
        dedupe_key_key=dedupe_key_key,
        passive=passive,
        active=active,
    )

