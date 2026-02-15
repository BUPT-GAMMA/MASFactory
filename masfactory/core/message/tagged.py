from __future__ import annotations

import json
import re
from typing import Any

from .base import StatefulFormatter, _best_effort_extract_object


class TaggedFieldMessageFormatter(StatefulFormatter):
    """
    Tag-based stateful message formatter.

    Output format (no closing tags, no JSON wrapper):
        <key1>value1<key2>value2

    Parsing rules:
    - All text before the first recognized tag is ignored.
    - Each recognized tag starts a new field. The field value continues until the next recognized tag.
    - Unknown tags are treated as plain text (part of the nearest field value).
    - Missing required fields are filled with empty strings (or best-effort fallbacks).
    """

    def __init__(self):
        super().__init__()
        # NOTE: `agent_introducer` is guarded by `is_input_formatter` in the base class,
        # even though we primarily use it to instruct output formatting.
        self._is_input_formatter = True
        self._is_output_formatter = True
        self._tag_pattern: re.Pattern[str] | None = None
        self._agent_introducer = (
            "Return tagged fields (NOT JSON). Format: <field_name>field_value ... "
            "The parser will ignore any text before the first tag."
        )

    def set_field_keys(self, field_keys: dict[str, str] | None) -> None:  # type: ignore[override]
        """Set the required field keys and rebuild the tag parser.

        Args:
            field_keys: Mapping of output field name -> description. When None, clears the
                current schema and disables tag parsing.
        """
        super().set_field_keys(field_keys)

        keys = list(self.field_keys.keys())
        if keys:
            # Match only expected tags to avoid breaking when values contain other angle-bracket text.
            # Prefer longer keys first to avoid partial matches in alternations.
            escaped = "|".join(sorted((re.escape(k) for k in keys), key=len, reverse=True))
            self._tag_pattern = re.compile(rf"<\s*(?P<key>{escaped})\s*>")
        else:
            self._tag_pattern = None

        self._agent_introducer = self._build_agent_introducer(self.field_keys)

    def _build_agent_introducer(self, field_keys: dict[str, str]) -> str:
        if not field_keys:
            return (
                "Return tagged fields (NOT JSON). Format: <field_name>field_value ... "
                "The parser will ignore any text before the first tag."
            )

        keys = list(field_keys.keys())
        tags = " ".join(f"<{k}>" for k in keys)

        # Keep the instructions explicit and robust across models.
        lines: list[str] = [
            "Return your response using TAGGED FIELDS (NOT JSON).",
            "Rules:",
            "1) Start your response directly with the first tag. Do not write anything before it.",
            "2) Write each field as: <field_name>field_value",
            "3) Do NOT use closing tags like </field_name>.",
            "4) A field value may span multiple lines and ends right before the next tag starts.",
            "5) Avoid using '<' or '>' in field values; if needed, use &lt; and &gt;.",
            "",
            "Required tags:",
            tags,
            "",
            "Few-shot example (format only):",
        ]

        # Create a small, concrete example using the first few keys.
        example_parts: list[str] = []
        for key in keys[:3]:
            example_value = self._example_value_for_key(key)
            example_parts.append(f"<{key}>{example_value}")
        lines.append("\n".join(example_parts))

        return "\n".join(lines).strip()

    def _example_value_for_key(self, key: str) -> str:
        lk = key.lower()
        if lk in ("graph_design", "graphdesign"):
            return json.dumps({"Nodes": [], "Edges": []}, ensure_ascii=False)
        if lk in ("review_result", "reviewresult"):
            return json.dumps({"status": "APPROVED", "issues": []}, ensure_ascii=False)
        if "code" in lk or lk in ("solution", "codes"):
            return "def foo(x):\n    return x"
        if "summary" in lk:
            return "A short summary."
        if "reason" in lk:
            return "Brief reasoning."
        return "..."

    def _strip_think_blocks(self, text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def _fill_required_keys(self, parsed: dict[str, Any], raw_text: str) -> dict[str, Any]:
        required = list(self.field_keys.keys())
        if not required:
            return parsed

        # Heuristic fallback: when there is exactly one required field, keep the raw output.
        if len(required) == 1:
            parsed.setdefault(required[0], raw_text.strip())
        else:
            if "output" in required:
                parsed.setdefault("output", raw_text.strip())
            elif required:
                parsed.setdefault(required[0], raw_text.strip())
            for key in required:
                parsed.setdefault(key, "")
        return parsed

    def _parse_tagged_fields(self, text: str) -> dict[str, str] | None:
        if not self._tag_pattern:
            return None

        matches = list(self._tag_pattern.finditer(text))
        if not matches:
            return None

        # Ignore all content before the first recognized tag.
        text = text[matches[0].start() :]
        matches = list(self._tag_pattern.finditer(text))
        if not matches:
            return None

        result: dict[str, str] = {}
        for i, match in enumerate(matches):
            key = match.group("key")
            value_start = match.end()
            value_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            value = text[value_start:value_end].strip()
            if key in result and value:
                result[key] = (result[key].rstrip() + "\n" + value).strip()
            elif key not in result:
                result[key] = value
        return result

    def format(self, message: object) -> dict:  # type: ignore[override]
        self._require_field_keys_set()

        if isinstance(message, dict):
            parsed: dict[str, Any] = dict(message)
            return self._fill_required_keys(parsed, json.dumps(message, ensure_ascii=False, default=str))

        raw = message if isinstance(message, str) else str(message)
        raw = self._strip_think_blocks(raw)
        if not raw:
            return self._fill_required_keys({}, "")

        parsed_tagged = self._parse_tagged_fields(raw)
        if parsed_tagged is not None:
            return self._fill_required_keys(dict(parsed_tagged), raw)

        # Compatibility fallback: if the model still returned a JSON/dict-like object.
        extracted = _best_effort_extract_object(raw)
        if isinstance(extracted, dict) and extracted:
            return self._fill_required_keys(dict(extracted), raw)

        # Last resort: fill required keys with best-effort raw text.
        return self._fill_required_keys({}, raw)

    def dump(self, message: dict) -> str:  # type: ignore[override]
        if isinstance(message, str):
            return message
        if not isinstance(message, dict):
            return str(message)

        # Prefer stable ordering based on configured field keys when available.
        keys: list[str]
        if getattr(self, "_field_keys_set", False) and self.field_keys:
            keys = list(self.field_keys.keys())
        else:
            keys = list(message.keys())

        parts: list[str] = []
        for key in keys:
            value = message.get(key, "")
            rendered = value if isinstance(value, str) else self.render_value(value)
            parts.append(f"<{key}>{rendered}")
        return "\n".join(parts).strip()
