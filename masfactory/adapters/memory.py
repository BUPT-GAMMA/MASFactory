from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

import numpy as np

from .context.provider import ContextProvider, HistoryProvider
from .context.types import ContextBlock, ContextQuery


class Memory(ContextProvider, ABC):
    """Base interface for memory backends.

    Memory is a long-lived stateful adapter that can both:
    - write: record information during a run (insert/update/delete/reset)
    - read: provide structured context blocks via `get_blocks(...)`
    """

    supports_passive: bool = True
    supports_active: bool = True

    def __init__(self, context_label: str, *, passive: bool = True, active: bool = False):
        self._context_label = context_label
        self.passive = passive
        self.active = active

    @property
    def context_label(self) -> str:
        return self._context_label

    @abstractmethod
    def insert(self, key: str, value: str):
        """Insert a new item into the memory."""

    @abstractmethod
    def update(self, key: str, value: str):
        """Update an existing item in the memory."""

    @abstractmethod
    def delete(self, key: str, index: int = -1):
        """Delete an item from the memory."""

    @abstractmethod
    def reset(self):
        """Clear in-memory state for this memory backend."""

    @abstractmethod
    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        """Return context blocks relevant to the query."""
        raise NotImplementedError


class HistoryMemory(Memory, HistoryProvider):
    """Conversation history memory (list-of-dict message format)."""

    supports_active: bool = False

    def __init__(self, top_k: int = 10, memory_size: int = 1000, context_label: str = "CONVERSATION_HISTORY"):
        super().__init__(context_label, passive=False, active=False)
        self._memory: list[dict] = []
        self._memory_size = int(memory_size)
        self._top_k = int(top_k)

    def insert(self, role: str, response: str):
        if self._memory_size > 0 and len(self._memory) >= self._memory_size:
            self._memory.pop(0)
        self._memory.append({"role": role, "content": response})

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        # HistoryMemory is carried via HistoryProvider.get_messages(), not injected as context blocks.
        return []

    def get_messages(self, query: ContextQuery | None = None, *, top_k: int = -1) -> list[dict]:
        if top_k == -1:
            top_k = self._top_k
        if top_k == 0:
            # 0 means "as many as possible" (bounded by memory_size when configured).
            if self._memory_size and self._memory_size > 0:
                top_k = min(self._memory_size, len(self._memory))
            else:
                top_k = len(self._memory)
        if top_k <= 0:
            return []
        return [dict(item) for item in self._memory[-top_k:]]

    def update(self, key: str, value: str):
        pass

    def delete(self, key: str, index: int = -1):
        if index != -1:
            self._memory.pop(index)
            return
        for i in range(len(self._memory) - 1, -1, -1):
            if self._memory[i].get("role") == key:
                self._memory.pop(i)
                return

    def reset(self):
        self._memory = []


class VectorMemory(Memory):
    """Semantic memory backed by embeddings and cosine similarity."""

    def __init__(
        self,
        embedding_function: Callable[[str], np.ndarray],
        top_k: int = 10,
        query_threshold: float = 0.8,
        memory_size: int = 20,
        context_label: str = "SEMANTIC_KNOWLEDGE",
        *,
        passive: bool = True,
        active: bool = False,
    ):
        super().__init__(context_label, passive=passive, active=active)
        self._embedding_function = embedding_function
        self._memory_size = int(memory_size)
        self._top_k = int(top_k)
        self._query_threshold = float(query_threshold)
        self._memory: dict[str, str] = {}
        self._embeddings: dict[str, np.ndarray] = {}

    def insert(self, key: str, value: str):
        if self._memory_size > 0 and len(self._memory) >= self._memory_size:
            oldest_key = next(iter(self._memory))
            self._memory.pop(oldest_key, None)
            self._embeddings.pop(oldest_key, None)

        self._memory[key] = value
        content_for_embedding = f"{key}: {value}"
        self._embeddings[key] = self._embedding_function(content_for_embedding)

    def update(self, key: str, value: str):
        if key not in self._memory:
            return
        self._memory[key] = value
        content_for_embedding = f"{key}: {value}"
        self._embeddings[key] = self._embedding_function(content_for_embedding)

    def delete(self, key: str, index: int = -1):
        self._memory.pop(key, None)
        self._embeddings.pop(key, None)

    def reset(self):
        self._memory = {}
        self._embeddings = {}

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        if not self._memory:
            return []

        query_text = (query.query_text or "").strip()
        if not query_text:
            return []

        query_embedding = self._embedding_function(query_text)
        threshold = self._query_threshold

        results: list[tuple[str, str, float]] = []
        for mem_key, mem_value in self._memory.items():
            mem_embedding = self._embeddings.get(mem_key)
            if mem_embedding is None:
                continue
            similarity = self._cosine_similarity(query_embedding, mem_embedding)
            if similarity >= threshold:
                results.append((mem_key, mem_value, similarity))

        results.sort(key=lambda x: x[2], reverse=True)

        limit = self._top_k if top_k == -1 else int(top_k)
        if limit == 0:
            limit = len(results)
        if limit < 0:
            return []

        blocks: list[ContextBlock] = []
        for key, value, score in results[:limit]:
            blocks.append(ContextBlock(text=str(value), score=float(score), metadata={"key": key}))
        return blocks

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)

        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))

