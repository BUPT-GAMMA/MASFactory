from __future__ import annotations

from abc import ABC, abstractmethod
import ast
from dataclasses import asdict, is_dataclass
import json
import threading
from typing import Any

def _coerce_to_basic_types(value: Any) -> Any:
    """Convert common rich objects to JSON-serializable primitives."""
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        return value.model_dump()
    if hasattr(value, "dict") and callable(getattr(value, "dict")):
        return value.dict()
    return value

def _json_default(value: Any) -> str:
    """Fallback JSON serializer for unknown object types."""
    try:
        return str(value)
    except Exception:
        return f"<unserializable {type(value).__name__}>"

def _default_render_value(value: Any) -> str:
    """Render a value as stable text for prompts."""
    value = _coerce_to_basic_types(value)
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, set):
        value = sorted(value, key=str)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=_json_default,
        ).rstrip()
    except Exception:
        return str(value)

class MessageFormatter(ABC):
    """Base interface for message parsing and rendering."""

    def __init__(self):
        self._agent_introducer: str | None = None
        self._is_input_formatter: bool = False
        self._is_output_formatter: bool = False

    @abstractmethod
    def format(self, message: str) -> dict:  # type: ignore
        """Parse model output text into structured dict payload."""
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    def dump(self, message: dict) -> str:
        """Render structured payload into text for model input."""
        raise NotImplementedError("Subclasses must implement this method")

    def render_value(self, value: Any) -> str:

        return _default_render_value(value)

    @property
    def agent_introducer(self) -> str:
        if not self._is_input_formatter:
            raise ValueError("This is not an input formatter")
        if self._agent_introducer is None:
            raise ValueError("Agent introducer is not set")
        return self._agent_introducer

    @property
    def is_input_formatter(self) -> bool:
        if self._agent_introducer is None:
            return False
        if self._is_input_formatter:
            return True
        return False

    @property
    def is_output_formatter(self) -> bool:
        if self._is_output_formatter:
            return True
        return False

class StatelessFormatter(MessageFormatter):
    """Singleton formatter base class for stateless formatters."""

    # NodeTemplate scoping: stateless formatters are safe to share across nodes.
    __node_template_scope__ = "shared"

    _instance = None
    _lock = threading.Lock()

    # Singleton implementation (per-subclass)
    def __new__(cls, *args, **kwargs) -> StatelessFormatter:  # type: ignore[override]
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

class StatefulFormatter(MessageFormatter):
    """Formatter base class whose output schema is set at runtime."""

    def __init__(self):
        super().__init__()
        self._field_keys: dict[str, str] = {}
        self._field_keys_set: bool = False

    def set_field_keys(self, field_keys: dict[str, str] | None) -> None:
        """Set the output field schema used by this formatter.

        Stateful formatters require a list of expected output fields before they can reliably
        parse or fan-out model outputs. Callers should set field keys once during node build
        (or before the first format call) and keep them stable for the lifetime of the node.

        Args:
            field_keys: Mapping of output field name -> human-readable description.
                When None, clears the current schema.
        """
        self._field_keys = {} if field_keys is None else dict(field_keys)
        self._field_keys_set = True

    @property
    def field_keys(self) -> dict[str, str]:
        return self._field_keys

    def _require_field_keys_set(self) -> None:
        if not self._field_keys_set:
            raise ValueError("StatefulFormatter requires calling set_field_keys(...) before format().")

def _best_effort_extract_object(text: str) -> dict[str, Any] | None:
    """
    Best-effort extraction of the first JSON/Python-dict-like object from free-form text.
    Returns None if parsing fails.
    """

    stripped = text.strip()
    if not stripped:
        return None

    # Remove common fenced wrappers.
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = stripped[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except Exception:
        try:
            parsed = ast.literal_eval(candidate)
        except Exception:
            return None

    return parsed if isinstance(parsed, dict) else None
