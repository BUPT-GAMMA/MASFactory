from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

import json
import os

import numpy as np

from .context.provider import ContextProvider
from .context.types import ContextBlock, ContextQuery


class Retrieval(ContextProvider, ABC):
    """Read-only retrieval interface for external context (RAG)."""

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
    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        """Return structured context blocks relevant to the query."""
        raise NotImplementedError


class VectorRetriever(Retrieval):
    """In-memory semantic retriever based on embedding cosine similarity."""

    def __init__(
        self,
        documents: dict[str, str],
        embedding_function: Callable[[str], np.ndarray],
        *,
        similarity_threshold: float = 0.7,
        context_label: str = "VECTOR_RETRIEVER",
        passive: bool = True,
        active: bool = False,
    ):
        super().__init__(context_label, passive=passive, active=active)
        self._documents = dict(documents)
        self._embedding_function = embedding_function
        self._similarity_threshold = float(similarity_threshold)
        self._doc_embeddings: dict[str, np.ndarray] = {}
        self._precompute_embeddings()

    def _precompute_embeddings(self) -> None:
        for doc_id, content in self._documents.items():
            self._doc_embeddings[doc_id] = self._embedding_function(content)

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        query_text = (query.query_text or "").strip()
        if not query_text:
            return []

        ranked = self._ranked_docs(query_text)
        limit = len(ranked) if int(top_k) == 0 else max(int(top_k), 0)
        if limit <= 0:
            return []

        blocks: list[ContextBlock] = []
        for doc_id, score in ranked[:limit]:
            text = self._documents.get(doc_id, "")
            if not text:
                continue
            blocks.append(ContextBlock(text=text, uri=str(doc_id), score=float(score), metadata={"doc_id": doc_id}))
        return blocks

    def _ranked_docs(self, query_text: str) -> list[tuple[str, float]]:
        query_embedding = self._embedding_function(query_text)
        scored: list[tuple[str, float]] = []
        for doc_id, doc_embedding in self._doc_embeddings.items():
            similarity = self._cosine_similarity(query_embedding, doc_embedding)
            if similarity >= self._similarity_threshold:
                scored.append((doc_id, float(similarity)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))


class FileSystemRetriever(Retrieval):
    """File-system retriever that indexes files in a directory and retrieves by embeddings."""

    def __init__(
        self,
        docs_dir: str | Path,
        embedding_function: Callable[[str], np.ndarray],
        *,
        file_extension: str = ".txt",
        similarity_threshold: float = 0.7,
        cache_path: str | Path | None = None,
        context_label: str = "FILESYSTEM_RETRIEVER",
        passive: bool = True,
        active: bool = False,
    ):
        super().__init__(context_label, passive=passive, active=active)
        self._docs_dir = Path(docs_dir)
        self._embedding_function = embedding_function
        self._file_extension = file_extension
        self._similarity_threshold = float(similarity_threshold)
        self._cache_path = Path(cache_path) if cache_path else None

        self._documents: dict[str, str] = {}
        self._doc_embeddings: dict[str, np.ndarray] = {}
        self._load_documents()

    def _load_documents(self) -> None:
        if self._cache_path and self._cache_path.exists():
            try:
                data = json.loads(self._cache_path.read_text(encoding="utf-8"))
                docs = data.get("documents")
                embs = data.get("embeddings")
                if isinstance(docs, dict) and isinstance(embs, dict):
                    self._documents = {str(k): str(v) for k, v in docs.items()}
                    self._doc_embeddings = {str(k): np.array(v) for k, v in embs.items()}
                    return
            except Exception:
                # Fall through to full reload.
                pass

        self._documents = {}
        self._doc_embeddings = {}
        if not self._docs_dir.exists():
            return

        for root, _, files in os.walk(str(self._docs_dir)):
            for fname in files:
                if not fname.endswith(self._file_extension):
                    continue
                path = Path(root) / fname
                try:
                    content = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                rel_id = str(path.relative_to(self._docs_dir))
                self._documents[rel_id] = content
                self._doc_embeddings[rel_id] = self._embedding_function(content)

        if self._cache_path:
            try:
                payload = {
                    "documents": self._documents,
                    "embeddings": {k: v.tolist() for k, v in self._doc_embeddings.items()},
                }
                self._cache_path.parent.mkdir(parents=True, exist_ok=True)
                self._cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        query_text = (query.query_text or "").strip()
        if not query_text:
            return []

        ranked = self._ranked_docs(query_text)
        limit = len(ranked) if int(top_k) == 0 else max(int(top_k), 0)
        if limit <= 0:
            return []

        blocks: list[ContextBlock] = []
        for doc_id, score in ranked[:limit]:
            text = self._documents.get(doc_id, "")
            if not text:
                continue
            blocks.append(ContextBlock(text=text, uri=str(doc_id), score=float(score), metadata={"doc_id": doc_id}))
        return blocks

    def _ranked_docs(self, query_text: str) -> list[tuple[str, float]]:
        query_embedding = self._embedding_function(query_text)
        scored: list[tuple[str, float]] = []
        for doc_id, doc_embedding in self._doc_embeddings.items():
            similarity = self._cosine_similarity(query_embedding, doc_embedding)
            if similarity >= self._similarity_threshold:
                scored.append((doc_id, float(similarity)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))


class SimpleKeywordRetriever(Retrieval):
    """Lightweight keyword-frequency retriever for small corpora."""

    def __init__(
        self,
        documents: dict[str, str],
        *,
        context_label: str = "KEYWORD_RETRIEVER",
        passive: bool = True,
        active: bool = False,
    ):
        super().__init__(context_label, passive=passive, active=active)
        self._documents = dict(documents)

    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]:
        query_text = (query.query_text or "").strip()
        if not query_text:
            return []

        scored = self._ranked_docs(query_text)
        limit = len(scored) if int(top_k) == 0 else max(int(top_k), 0)
        if limit <= 0:
            return []

        blocks: list[ContextBlock] = []
        for doc_id, score in scored[:limit]:
            text = self._documents.get(doc_id, "")
            if not text:
                continue
            blocks.append(ContextBlock(text=text, uri=str(doc_id), score=float(score), metadata={"doc_id": doc_id}))
        return blocks

    def _ranked_docs(self, query_text: str) -> list[tuple[str, float]]:
        scores: list[tuple[str, float]] = []
        for doc_id, content in self._documents.items():
            scores.append((doc_id, float(self._compute_relevance(query_text, content))))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def _compute_relevance(self, query: str, document: str) -> float:
        query_lower = query.lower()
        document_lower = (document or "").lower()
        if not document_lower:
            return 0.0
        words = [w for w in query_lower.split() if w]
        count = 0
        for word in words:
            count += document_lower.count(word)
        if query_lower in document_lower:
            count += len(words) * 2
        return count / (len(document_lower.split()) + 1)

