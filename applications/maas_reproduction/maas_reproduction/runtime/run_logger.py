"""Small structured file logger for one MaAS run.

The logger intentionally accepts only public, scalar run metadata.  It does
not serialize graph state, prompts, model responses, or evaluator inputs.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


_SENSITIVE_VALUE = re.compile(
    r"(?i)(api[_ -]?key|authorization|bearer)\s*[:=]\s*[^,\s]+"
)
_SENSITIVE_LABEL = re.compile(r"(?i)(prompt|expected[_ -]?answer)\s*[:=].*")


def _safe_text(value: Any, *, limit: int = 500) -> str:
    text = str(value)
    text = _SENSITIVE_VALUE.sub(r"\1=[REDACTED]", text)
    text = _SENSITIVE_LABEL.sub(r"\1=[REDACTED]", text)
    return text[:limit]


class RunLogger:
    """Append public lifecycle events to ``run.log`` and ``error.log``."""

    def __init__(self, root: str | Path, run_id: str) -> None:
        self.root = Path(root)
        self.directory = self.root / "logs"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.run_id = _safe_text(run_id, limit=120)
        self.run_path = self.directory / "run.log"
        self.error_path = self.directory / "error.log"

    def _write(self, path: Path, event: str, fields: Mapping[str, Any]) -> None:
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event": event,
        }
        for key, value in fields.items():
            if key in {"prompt", "expected_answer", "response", "route_state", "dispatch_state"}:
                continue
            if key in {"error", "message", "failure_detail"}:
                record[key] = _safe_text(value)
            else:
                record[key] = value
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def event(self, event: str, **fields: Any) -> None:
        self._write(self.run_path, event, fields)

    def error(self, *, stage: str, error: BaseException | str, **fields: Any) -> None:
        error_type = type(error).__name__ if isinstance(error, BaseException) else "RuntimeError"
        message = str(error)
        payload = dict(fields)
        payload.update({"stage": stage, "error_type": error_type, "message": _safe_text(message)})
        self._write(self.error_path, "error", payload)
        self._write(self.run_path, "error", payload)


__all__ = ["RunLogger"]
