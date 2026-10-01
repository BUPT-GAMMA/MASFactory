"""Small adapter helpers shared by Programmer nodes."""
from __future__ import annotations

import re
from typing import Any


_FENCED_CODE_RE = re.compile(
    r"```(?P<language>[A-Za-z0-9_+.-]*)[ \t]*\r?\n(?P<code>.*?)```",
    flags=re.DOTALL,
)


def call_adapter(adapter: Any, payload: dict[str, Any]) -> Any:
    if adapter is None:
        raise RuntimeError("operator adapter is not configured")
    if hasattr(adapter, "invoke"):
        value = adapter.invoke(payload)
        return value[0] if isinstance(value, tuple) else value
    if callable(adapter):
        return adapter(payload)
    raise TypeError("operator adapter must expose invoke() or be callable")


def extract_code(value: Any) -> str | None:
    """Return one conservative code candidate from an adapter response.

    Only an explicitly fenced Python (or unlabelled) block is unwrapped.  We do
    not try to repair arbitrary prose with regular expressions; syntax and the
    required interface are validated by ``ProgrammerCore.parse``.
    """
    if isinstance(value, str):
        candidate = value
    elif isinstance(value, dict):
        candidate = value.get("code") or value.get("solution") or value.get("response")
    else:
        candidate = (
            getattr(value, "code", None)
            or getattr(value, "solution", None)
            or getattr(value, "response", None)
        )
    if not isinstance(candidate, str):
        return candidate

    matches = list(_FENCED_CODE_RE.finditer(candidate))
    if not matches:
        return candidate.strip()
    preferred = next(
        (match for match in matches if match.group("language").lower() in {"python", "py"}),
        None,
    )
    if preferred is None:
        preferred = next((match for match in matches if not match.group("language")), None)
    return preferred.group("code").strip() if preferred is not None else candidate.strip()
