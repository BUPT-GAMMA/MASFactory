from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

import numpy as np

from .context.provider import ContextProvider, HistoryProvider
from .context.types import ContextBlock, ContextQuery
from masfactory.core.multimodal import MediaMessageBlock, TextMessageBlock, iter_media_message_blocks
from masfactory.checkpoint.checkpointable import Checkpointable
from copy import deepcopy

class Memory(ContextProvider,Checkpointable,ABC):
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
    def insert(self, key: str, value: object):
        """Insert a new item into the memory."""

    @abstractmethod
    def update(self, key: str, value: object):
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
    
    def get_checkpoint_state(self):
        return {
            "type":self.__class__.__name__,
            "context_label":self._context_label,
            "passive":self.passive,
            "active":self.active,
        }

    def load_checkpoint_state(self, state):
        self._context_label = state["context_label"]
        self.passive = state["passive"]
        self.active = state["active"]

class HistoryMemory(Memory, HistoryProvider):
    """Conversation history memory (list-of-dict message format)."""

    supports_active: bool = False

    def __init__(
        self,
        top_k: int = 10,
        memory_size: int = 1000,
        context_label: str = "CONVERSATION_HISTORY",
        *,
        merge_historical_media: bool = True,
    ):
        super().__init__(context_label, passive=False, active=False)
        self._memory: list[dict] = []
        self._memory_size = int(memory_size)
        self._top_k = int(top_k)
        self._merge_historical_media = bool(merge_historical_media)

    def insert(self, role: str, response: object):
        if self._memory_size > 0 and len(self._memory) >= self._memory_size:
            self._memory.pop(0)
        self._memory.append({"role": role, "content": response})

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        # HistoryMemory is carried via HistoryProvider.get_messages(), not injected as context blocks.
        return []

    def get_messages(self, query: ContextQuery | None = None, *, top_k: int = -1) -> list[dict]:
        del query
        if top_k == -1:
            top_k = self._top_k
        if top_k == 0:
            if self._memory_size and self._memory_size > 0:
                top_k = min(self._memory_size, len(self._memory))
            else:
                top_k = len(self._memory)
        if top_k <= 0:
            return []
        messages = [dict(item) for item in self._memory[-top_k:]]
        if not self._merge_historical_media:
            return messages
        return self._merge_media_messages(messages)

    def _merge_media_messages(self, messages: list[dict]) -> list[dict]:
        fingerprint_to_tag: dict[str, str] = {}
        merged_messages: list[dict] = []
        for message in messages:
            cloned = dict(message)
            content = cloned.get("content")
            if not isinstance(content, list):
                merged_messages.append(cloned)
                continue
            rewritten_content: list[object] = []
            seen_in_message: set[str] = set()
            for block in content:
                if not isinstance(block, MediaMessageBlock):
                    rewritten_content.append(block)
                    continue
                fingerprint = self._media_fingerprint_key(block)
                canonical_tag = fingerprint_to_tag.get(fingerprint)
                if canonical_tag is None:
                    fingerprint_to_tag[fingerprint] = block.tag
                    rewritten_content.append(block)
                    seen_in_message.add(fingerprint)
                    continue
                if canonical_tag == block.tag and fingerprint not in seen_in_message:
                    rewritten_content.append(TextMessageBlock(text=canonical_tag))
                    seen_in_message.add(fingerprint)
                    continue
                rewritten_content.append(TextMessageBlock(text=canonical_tag))
                seen_in_message.add(fingerprint)
            cloned["content"] = rewritten_content
            merged_messages.append(cloned)
        return merged_messages

    def _media_fingerprint_key(self, block: MediaMessageBlock) -> str:
        return block.fingerprint

    def update(self, key: str, value: object):
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

    def get_checkpoint_state(self):
        state=super().get_checkpoint_state()
        state.update({
            "memory":deepcopy(self._memory),
            "memory_size":self._memory_size ,
            "top_k":self._top_k,
            "merge_historical_media":self._merge_historical_media,
        })    
        return state

    def load_checkpoint_state(self, state):
        super().load_checkpoint_state(state)
        self._memory=deepcopy(state["memory"])
        self._memory_size = int(state["memory_size"])
        self._top_k = int(state["top_k"])
        self._merge_historical_media = bool(state["merge_historical_media"])

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

    def insert(self, key: str, value: object):
        if self._memory_size > 0 and len(self._memory) >= self._memory_size:
            oldest_key = next(iter(self._memory))
            self._memory.pop(oldest_key, None)
            self._embeddings.pop(oldest_key, None)

        text_value = str(value)
        self._memory[key] = text_value
        content_for_embedding = f"{key}: {text_value}"
        self._embeddings[key] = self._embedding_function(content_for_embedding)

    def update(self, key: str, value: object):
        if key not in self._memory:
            return
        text_value = str(value)
        self._memory[key] = text_value
        content_for_embedding = f"{key}: {text_value}"
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

    def get_checkpoint_state(self)->dict:
        state=super().get_checkpoint_state()
        state.update({
            "memory_size":self._memory_size,
            "top_k":self._top_k,
            "query_threshold":self._query_threshold,
            "memory":deepcopy(self._memory),
            "embeddings":{
                key:value.tolist() for key,value in self._embeddings.items()
            }
        })
        return state

    def load_checkpoint_state(self, state:dict)->None:
        super().load_checkpoint_state(state)
        self._memory_size = int(state["memory_size"])
        self._top_k = int(state["top_k"])
        self._query_threshold =float(state["query_threshold"])
        self._memory=deepcopy(state["memory"])
        self._embeddings={
            key:np.array(value) for key,value in state["embeddings"].items()
        }