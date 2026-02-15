from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextBlock:
    """One structured context unit to be injected into the user prompt."""

    text: str
    uri: str | None = None
    chunk_id: str | None = None
    score: float | None = None
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str | None = None


@dataclass(frozen=True, slots=True)
class ContextQuery:
    """Normalized query passed to context providers."""

    query_text: str
    inputs: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None
    node_name: str | None = None
    node_path: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    messages: list[dict] | None = None

