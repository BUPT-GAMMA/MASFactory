from __future__ import annotations

from abc import ABC, abstractmethod

from .types import ContextBlock, ContextQuery


class ContextProvider(ABC):
    """Base interface for all context sources (Memory / Retrieval / MCP)."""

    @abstractmethod
    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        """Return context blocks relevant to the query."""
        raise NotImplementedError


class HistoryProvider(ABC):
    """Provider for chat history messages (list-of-dict format)."""

    @abstractmethod
    def get_messages(self, query: ContextQuery | None = None, *, top_k: int = -1) -> list[dict]:
        """Return chat history messages for the current query."""
        raise NotImplementedError
