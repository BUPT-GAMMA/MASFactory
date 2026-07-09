"""
Browser Game Agent — cross-session lesson memory.

Persists distilled "lessons" (a recurring bug/design pitfall -> how to avoid or fix it) to
disk so that *later* game sessions can proactively avoid known pitfalls (injected at Planning
/ Coding) and reuse known fixes (injected at Fix). This is the one form of memory the app did
not previously have: intra-phase chat history, inter-phase attribute state, and per-session
disk artifacts all exist already, but nothing carried learning *across* games.

Retrieval reuses MASFactory's ``SimpleKeywordRetriever`` by default (same pattern as
``components/retrieval.py``). An optional embedding-backed ``VectorRetriever`` path is enabled
with ``BGA_LESSON_EMBEDDINGS=1`` and falls back to keyword retrieval on any failure.

Capture prefers a single LLM distillation pass (``distill_and_record``) that turns this
session's test issues into structured lessons; if the LLM call or its parsing fails, it falls
back to recording the raw issue strings so no signal is lost.
"""

from __future__ import annotations

import os
import re
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = 5
_SIMILARITY_THRESHOLD = 0.6  # Jaccard token overlap for treating two lessons as the same.


def _tokens(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if len(t) > 2]


def _extract_json_object(text: str) -> Optional[dict]:
    """Best-effort extraction of a JSON object from possibly fenced LLM output."""
    if not isinstance(text, str):
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    # Fall back to the first balanced {...} span.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start:end + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


class LessonStore:
    """Load/save/retrieve/record cross-session lessons backed by a JSON file."""

    def __init__(self, path: str, *, api_key: str = "", base_url: str = ""):
        self.path = str(path)
        self._api_key = api_key or ""
        self._base_url = base_url or ""
        self._lessons: List[dict] = self._load()

    # ------------------------------------------------------------------ storage
    def _load(self) -> List[dict]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning("LessonStore: failed to load %s: %s", self.path, exc)
            return []
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            return [d for d in (data.get("lessons") or []) if isinstance(d, dict)]
        return []

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._lessons, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("LessonStore: failed to save %s: %s", self.path, exc)

    def __len__(self) -> int:
        return len(self._lessons)

    # ---------------------------------------------------------------- retrieval
    def retrieve(self, query: str, top_k: int = _DEFAULT_TOP_K) -> str:
        """Return a formatted text block of the most relevant lessons, or "" if none."""
        if not self._lessons or not str(query or "").strip():
            return ""
        limit = max(1, int(top_k))
        docs = {self._doc_id(i): self._doc_text(l) for i, l in enumerate(self._lessons)}
        blocks = self._rank(str(query), docs, limit)
        if not blocks:
            return ""
        lines = []
        for block in blocks:
            doc_id = getattr(block, "uri", "") or getattr(block, "metadata", {}).get("doc_id", "")
            lesson = self._lesson_for(doc_id)
            if lesson is None:
                continue
            lines.append(self._format_lesson(lesson))
        return "\n".join(lines)

    def _rank(self, query: str, docs: Dict[str, str], limit: int):
        # Optional embedding-backed retrieval; keyword is the robust default.
        if os.getenv("BGA_LESSON_EMBEDDINGS", "").strip().lower() in {"1", "true", "yes", "on"}:
            try:
                return self._rank_vector(query, docs, limit)
            except Exception as exc:
                logger.warning("LessonStore: vector retrieval unavailable, using keyword: %s", exc)
        try:
            from masfactory.adapters.context.types import ContextQuery
            from masfactory.adapters.retrieval import SimpleKeywordRetriever

            retriever = SimpleKeywordRetriever(docs, context_label="LESSON_RETRIEVER")
            return retriever.get_blocks(ContextQuery(query_text=query), top_k=limit)
        except Exception as exc:
            logger.warning("LessonStore: keyword retriever unavailable, using manual rank: %s", exc)
            return self._rank_manual(query, docs, limit)

    def _rank_vector(self, query: str, docs: Dict[str, str], limit: int):
        from masfactory.adapters.context.types import ContextQuery
        from masfactory.adapters.retrieval import VectorRetriever

        embed = self._build_embedding_function()
        retriever = VectorRetriever(docs, embed, context_label="LESSON_VECTOR_RETRIEVER")
        return retriever.get_blocks(ContextQuery(query_text=query), top_k=limit)

    def _build_embedding_function(self):
        """Build an embedding function from the same OpenAI-compatible endpoint."""
        import numpy as np
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key or None, base_url=self._base_url or None)
        model_name = os.getenv("BGA_EMBEDDING_MODEL", "text-embedding-3-small")

        def embed(text: str) -> "np.ndarray":
            resp = client.embeddings.create(model=model_name, input=str(text or ""))
            return np.array(resp.data[0].embedding, dtype=float)

        return embed

    def _rank_manual(self, query: str, docs: Dict[str, str], limit: int):
        q = set(_tokens(query))
        scored = []
        for doc_id, text in docs.items():
            overlap = len(q & set(_tokens(text)))
            scored.append((doc_id, text, float(overlap)))
        scored.sort(key=lambda item: item[2], reverse=True)
        return [
            type("Block", (), {"uri": doc_id, "text": text, "score": score, "metadata": {"doc_id": doc_id}})()
            for doc_id, text, score in scored[:limit]
            if score > 0
        ]

    # ------------------------------------------------------------------ capture
    def distill_and_record(self, model, context: Dict[str, Any], example: str = "") -> int:
        """Distill this session's issues into lessons (one LLM call) and persist them.

        Returns the number of lessons recorded. No-op (returns 0) when the session had no
        reported issues. Falls back to raw-issue capture if LLM distillation fails.
        """
        combined = self._combined_issues(context)
        if not combined:
            return 0
        lessons = self._distill_via_llm(model, context, combined)
        if not lessons:
            lessons = [
                {"pattern": self._short_pattern(issue), "symptom": issue, "fix": "", "tags": []}
                for issue in combined
            ]
        self.record_lessons(lessons, example=example)
        return len(lessons)

    def record_lessons(self, lessons: List[dict], example: str = "") -> None:
        changed = False
        for lesson in lessons or []:
            if isinstance(lesson, dict) and self._merge_one(lesson, example):
                changed = True
        if changed:
            self._save()

    def _distill_via_llm(self, model, context: Dict[str, Any], combined: List[str]) -> List[dict]:
        try:
            from applications.browser_game_agent.components.schemas import (
                LessonListSchema,
                schema_as_text,
            )

            prompt = (
                "You maintain a cross-project memory of recurring browser-game bugs so future "
                "games avoid them. From this session's data, distill DISTINCT, GENERALIZABLE "
                "lessons (skip one-off/game-specific noise). Return ONLY JSON matching this "
                "schema:\n"
                f"{schema_as_text(LessonListSchema)}\n\n"
                f"Game task: {context.get('task', '')}\n"
                f"UI issues: {context.get('ui_issues')}\n"
                f"Functional issues: {context.get('functional_issues')}\n"
                f"Test rounds summary: {context.get('test_results', '')}\n"
                'Respond with: {"lessons": [{"pattern": "...", "symptom": "...", '
                '"fix": "...", "tags": ["..."]}]}'
            )
            resp = model.invoke(messages=[{"role": "user", "content": prompt}], tools=None)
            content = resp.get("content") if isinstance(resp, dict) else None
            data = _extract_json_object(content) if isinstance(content, str) else None
            if not data:
                return []
            lessons = data.get("lessons")
            return [l for l in lessons if isinstance(l, dict)] if isinstance(lessons, list) else []
        except Exception as exc:
            logger.warning("LessonStore: LLM distillation failed, will fall back: %s", exc)
            return []

    def _merge_one(self, lesson: dict, example: str) -> bool:
        pattern = str(lesson.get("pattern") or "").strip()
        symptom = str(lesson.get("symptom") or "").strip()
        if not (pattern or symptom):
            return False
        for existing in self._lessons:
            if self._is_similar(existing, pattern, symptom):
                existing["count"] = int(existing.get("count", 1)) + 1
                examples = existing.setdefault("examples", [])
                if example and example not in examples:
                    examples.append(example)
                if not existing.get("fix") and lesson.get("fix"):
                    existing["fix"] = str(lesson["fix"]).strip()
                return True
        self._lessons.append(
            {
                "id": self._new_id(pattern, symptom),
                "pattern": pattern,
                "symptom": symptom,
                "fix": str(lesson.get("fix") or "").strip(),
                "tags": [str(t) for t in (lesson.get("tags") or []) if str(t).strip()],
                "count": 1,
                "examples": [example] if example else [],
            }
        )
        return True

    def _is_similar(self, existing: dict, pattern: str, symptom: str) -> bool:
        a = set(_tokens(f"{existing.get('pattern', '')} {existing.get('symptom', '')}"))
        b = set(_tokens(f"{pattern} {symptom}"))
        if not a or not b:
            return False
        return len(a & b) / len(a | b) >= _SIMILARITY_THRESHOLD

    # -------------------------------------------------------------- small utils
    @staticmethod
    def _combined_issues(context: Dict[str, Any]) -> List[str]:
        out: List[str] = []
        for key in ("ui_issues", "functional_issues"):
            val = context.get(key)
            if isinstance(val, list):
                out.extend(str(v).strip() for v in val if str(v).strip())
            elif isinstance(val, str) and val.strip():
                out.append(val.strip())
        # De-dup preserving order.
        seen, unique = set(), []
        for item in out:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique

    @staticmethod
    def _short_pattern(issue: str) -> str:
        words = str(issue or "").split()
        return " ".join(words[:6]) if words else "unknown"

    @staticmethod
    def _new_id(pattern: str, symptom: str) -> str:
        import hashlib

        return hashlib.sha1(f"{pattern}|{symptom}".encode("utf-8")).hexdigest()[:12]

    def _doc_id(self, index: int) -> str:
        return self._lessons[index].get("id") or f"lesson_{index}"

    @staticmethod
    def _doc_text(lesson: dict) -> str:
        parts = [lesson.get("pattern", ""), lesson.get("symptom", ""), lesson.get("fix", "")]
        parts.extend(lesson.get("tags", []) or [])
        return "\n".join(str(p) for p in parts if p)

    def _lesson_for(self, doc_id: str) -> Optional[dict]:
        for lesson in self._lessons:
            if (lesson.get("id") or "") == doc_id:
                return lesson
        # doc_id may be the positional fallback "lesson_<i>".
        if isinstance(doc_id, str) and doc_id.startswith("lesson_"):
            try:
                return self._lessons[int(doc_id.split("_", 1)[1])]
            except Exception:
                return None
        return None

    @staticmethod
    def _format_lesson(lesson: dict) -> str:
        pattern = lesson.get("pattern") or "pitfall"
        symptom = lesson.get("symptom") or ""
        fix = lesson.get("fix") or ""
        count = int(lesson.get("count", 1))
        tail = f" -> Fix: {fix}" if fix else ""
        seen = f" (seen {count}x)" if count > 1 else ""
        return f"- [{pattern}] {symptom}{tail}{seen}".strip()


__all__ = ["LessonStore"]
