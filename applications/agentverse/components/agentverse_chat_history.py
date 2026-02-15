from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

from masfactory.adapters.memory import HistoryMemory


@dataclass
class AgentverseSharedHistoryState:
    """Shared, thread-safe buffer for AgentVerse-style chat history."""

    memory: list[dict[str, str]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    memory_size: int = 1000


class AgentverseSharedChatHistoryMemory(HistoryMemory):
    """
    AgentVerse-style chat history memory:
    - Stores ONLY assistant outputs (skips storing full user prompts to reduce noise).
    - Prefixes each stored message with "[{sender}]:", similar to original AgentVerse.
    - Multiple instances can share a single underlying history buffer.
    """

    def __init__(
        self,
        *,
        shared_state: AgentverseSharedHistoryState,
        sender: str,
        top_k: int = 8,
        memory_size: int = 1000,
        context_label: str = "CONVERSATION_HISTORY",
    ):
        super().__init__(top_k=top_k, memory_size=memory_size, context_label=context_label)
        self._shared_state = shared_state
        self._sender = str(sender or "Agent").strip() or "Agent"

        # Keep the shared size consistent with the configured memory_size.
        if int(memory_size) > 0:
            self._shared_state.memory_size = int(memory_size)

    def _looks_like_critic(self) -> bool:
        return "critic" in self._sender.lower()

    def _strip_code_fences(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n")
        blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", normalized, re.DOTALL | re.IGNORECASE)
        if blocks:
            return blocks[-1].strip()
        blocks = re.findall(r"```(?:python|py)?\s*(.*?)```", normalized, re.DOTALL | re.IGNORECASE)
        if blocks:
            return blocks[-1].strip()
        return text.strip()

    def _normalize_assistant_output(self, text: str) -> str:
        """
        Match original AgentVerse memory semantics:
        - Critics: do NOT store agree messages; store only cleaned criticism (strip [Disagree]).
        - Solver: store parsed code content (strip ``` fences) when present.
        """
        raw = text if isinstance(text, str) else str(text)
        stripped = raw.strip()
        if not stripped:
            return ""

        if self._looks_like_critic():
            lowered = stripped.lower()
            # Original AgentVerse parses `[Agree]` to is_agree=True and does not broadcast/store it.
            if "[agree]" in lowered:
                return ""
            cleaned = stripped
            cleaned = cleaned.replace("[Disagree]", "").replace("[disagree]", "")
            cleaned = cleaned.replace("[Agree]", "").replace("[agree]", "")
            return cleaned.strip()

        # Solver (and non-critic) messages: keep code content, not markdown fences.
        if "```" in stripped:
            return self._strip_code_fences(stripped)
        return stripped

    def insert(self, role: str, response: str):  # type: ignore[override]
        # AgentVerse memory stores message contents (not full prompts). Skip "user" prompt inserts.
        if role != "assistant":
            return

        content = response if isinstance(response, str) else str(response)
        content = self._normalize_assistant_output(content)
        if not content:
            return
        prefix = f"[{self._sender}]: "
        if not content.startswith(prefix):
            content = prefix + content

        with self._shared_state.lock:
            mem = self._shared_state.memory
            if len(mem) >= self._shared_state.memory_size:
                mem.pop(0)
            mem.append({"role": "assistant", "content": content})

    def query(self, key: Any, top_k: int = -1, threshold: float = 0.8) -> list:  # type: ignore[override]
        if top_k == -1:
            top_k = self._top_k
        if top_k == 0:
            top_k = self._shared_state.memory_size
        if top_k <= 0:
            return []
        with self._shared_state.lock:
            return list(self._shared_state.memory[-top_k:])

    def reset(self):  # type: ignore[override]
        with self._shared_state.lock:
            self._shared_state.memory.clear()
