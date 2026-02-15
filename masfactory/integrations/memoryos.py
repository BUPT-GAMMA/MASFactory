from __future__ import annotations

from typing import Any, Callable, Iterable

from masfactory.adapters.context.types import ContextBlock, ContextQuery
from masfactory.adapters.mcp import MCP
from masfactory.adapters.memory import Memory


class MemoryOSMemory(Memory):
    """MemoryOS integration via a native (in-process) memory wrapper.

    This adapter avoids importing MemoryOS directly. You inject callables to integrate with
    your MemoryOS client. MASFactory will call `insert(...)` after each agent step.

    For reads, you provide `retrieve(...)` which returns iterable items mapped to ContextBlock.
    Recommended item shape mirrors `ContextBlock` fields.
    """

    def __init__(
        self,
        *,
        name: str = "MemoryOS",
        retrieve: Callable[[ContextQuery, int], Iterable[dict[str, Any]]],
        insert_fn: Callable[[str, str], None] | None = None,
        update_fn: Callable[[str, str], None] | None = None,
        delete_fn: Callable[[str, int], None] | None = None,
        reset_fn: Callable[[], None] | None = None,
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
        self._insert_fn = insert_fn
        self._update_fn = update_fn
        self._delete_fn = delete_fn
        self._reset_fn = reset_fn
        self._keys = {
            "text": text_key,
            "uri": uri_key,
            "chunk_id": chunk_id_key,
            "score": score_key,
            "title": title_key,
            "metadata": metadata_key,
            "dedupe_key": dedupe_key_key,
        }

    def insert(self, key: str, value: str):
        if self._insert_fn is None:
            raise NotImplementedError("MemoryOSMemory.insert requires insert_fn")
        self._insert_fn(key, value)

    def update(self, key: str, value: str):
        if self._update_fn is None:
            raise NotImplementedError("MemoryOSMemory.update requires update_fn")
        self._update_fn(key, value)

    def delete(self, key: str, index: int = -1):
        if self._delete_fn is None:
            raise NotImplementedError("MemoryOSMemory.delete requires delete_fn")
        self._delete_fn(key, index)

    def reset(self):
        if self._reset_fn is not None:
            self._reset_fn()

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


def make_memoryos_mcp(
    *,
    call: Callable[[ContextQuery, int], Iterable[dict[str, Any]]],
    name: str = "MemoryOS",
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
    """MemoryOS integration via MCP transport.

    Use this when MemoryOS runs out-of-process and you access it through an MCP tool/server.
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

