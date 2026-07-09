"""
Browser Game Agent Retrieval

Centralizes session-artifact retrieval so ask/modify flows share one path built on
MASFactory's retrieval adapters instead of duplicating ad-hoc file scanning.

Current backend: SimpleKeywordRetriever (lightweight keyword frequency), with a manual
keyword fallback if the adapter is unavailable. FileSystemRetriever / VectorRetriever can be
swapped in here (single call site) once an embedding function is wired up.
"""

from __future__ import annotations

import os
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# Priority order used when scanning a session directory for relevant artifacts.
_PRIORITY_ORDER = [
    "design.md",
    "index.html",
    "game.js",
    "style.css",
    "test_results.json",
    "IMPLEMENTATION.md",
    "README.md",
]

_ALLOWED_SUFFIXES = (".html", ".js", ".css", ".md", ".json")


def read_session_documents(directory: str) -> Dict[str, str]:
    """Return {filename: content} for readable artifacts in a session directory.

    Skips hidden files (e.g. .test_checkpoints.json) and non-source extensions, ordering
    the well-known game artifacts first so keyword ties resolve to the more meaningful file.
    """
    if not directory or not os.path.exists(directory):
        return {}
    docs: Dict[str, str] = {}
    all_files = sorted(os.listdir(directory))
    ordered = _PRIORITY_ORDER + [f for f in all_files if f not in _PRIORITY_ORDER]
    for filename in ordered:
        path = os.path.join(directory, filename)
        if not os.path.isfile(path) or filename.startswith("."):
            continue
        if not filename.endswith(_ALLOWED_SUFFIXES):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                docs[filename] = f.read()
        except Exception as exc:
            logger.warning("retrieval: failed to read %s: %s", path, exc)
            continue
    return docs


def retrieve_session_context(query: str, top_k: int = 6, directory: Optional[str] = None) -> str:
    """Retrieve the most relevant session artifacts for a query as a formatted block.

    Uses MASFactory's SimpleKeywordRetriever over the session artifacts, keeping ask/modify
    prompts grounded without blindly injecting every file. Falls back to a manual keyword
    frequency ranking if the retriever adapter cannot be imported.

    Args:
        query: The question or modification request driving retrieval.
        top_k: Maximum number of artifacts to return.
        directory: Session directory to scan. Required.

    Returns:
        A newline-joined string of "=== <uri> (score=..) ===\\n<content>" blocks, or an
        informational message if nothing is available.
    """
    docs = read_session_documents(directory or "")
    if not docs:
        return "No output files found in the game directory."

    limit = max(1, int(top_k))
    blocks = _rank_documents(query, docs, limit)
    if not blocks:
        blocks = [
            type("Block", (), {"uri": name, "text": content, "score": 0.0})()
            for name, content in list(docs.items())[:limit]
        ]

    parts = []
    for block in blocks:
        uri = getattr(block, "uri", "") or getattr(block, "metadata", {}).get("doc_id", "artifact")
        score = getattr(block, "score", 0.0)
        text = getattr(block, "text", "")
        parts.append(f"=== {uri} (score={score:.4f}) ===\n{text}")
    return "\n\n".join(parts)


def _rank_documents(query: str, docs: Dict[str, str], limit: int):
    """Rank docs via SimpleKeywordRetriever, falling back to manual keyword frequency."""
    try:
        from masfactory.adapters.context.types import ContextQuery
        from masfactory.adapters.retrieval import SimpleKeywordRetriever

        retriever = SimpleKeywordRetriever(
            docs,
            context_label="SESSION_ARTIFACT_RETRIEVER",
            passive=True,
            active=False,
        )
        return retriever.get_blocks(ContextQuery(query_text=str(query or "")), top_k=limit)
    except Exception as exc:
        logger.warning("retrieval: SimpleKeywordRetriever unavailable, using manual rank: %s", exc)
        query_words = [w for w in str(query or "").lower().split() if w]
        ranked = []
        for name, content in docs.items():
            haystack = (name + "\n" + content).lower()
            score = sum(haystack.count(word) for word in query_words)
            ranked.append((name, content, float(score)))
        ranked.sort(key=lambda item: item[2], reverse=True)
        return [
            type("Block", (), {"uri": name, "text": content, "score": score})()
            for name, content, score in ranked[:limit]
        ]


__all__ = ["read_session_documents", "retrieve_session_context"]
