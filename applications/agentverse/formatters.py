from __future__ import annotations

import re

from masfactory.core.message import TwinsFieldTextFormatter


def _unescape_newlines_outside_strings(text: str) -> str:
    """Convert literal '\\n' (and '\\r\\n') sequences into real newlines, but only outside strings."""

    if "\\n" not in text and "\\r\\n" not in text:
        return text

    out: list[str] = []
    i = 0
    state: str | None = None  # None | "single" | "double" | "triple_single" | "triple_double"
    escaped = False

    while i < len(text):
        if state is None:
            if text.startswith("'''", i):
                out.append("'''")
                state = "triple_single"
                i += 3
                continue
            if text.startswith('"""', i):
                out.append('"""')
                state = "triple_double"
                i += 3
                continue

            ch = text[i]
            if ch == "'":
                out.append(ch)
                state = "single"
                escaped = False
                i += 1
                continue
            if ch == '"':
                out.append(ch)
                state = "double"
                escaped = False
                i += 1
                continue

            # Unescape newline escapes outside any string literal.
            if text.startswith("\\r\\n", i):
                out.append("\n")
                i += 4
                continue
            if text.startswith("\\n", i):
                out.append("\n")
                i += 2
                continue

            out.append(ch)
            i += 1
            continue

        if state == "triple_single":
            if text.startswith("'''", i):
                out.append("'''")
                state = None
                i += 3
                continue
            out.append(text[i])
            i += 1
            continue

        if state == "triple_double":
            if text.startswith('"""', i):
                out.append('"""')
                state = None
                i += 3
                continue
            out.append(text[i])
            i += 1
            continue

        # single/double quoted strings: keep literal characters, track escapes.
        ch = text[i]
        out.append(ch)
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif state == "single" and ch == "'":
            state = None
        elif state == "double" and ch == '"':
            state = None
        i += 1

    return "".join(out)


def _extract_python_code(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n")

    # Prefer the last fenced code block (with or without language tag).
    code_blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", normalized, re.DOTALL | re.IGNORECASE)
    if code_blocks:
        return _unescape_newlines_outside_strings(code_blocks[-1].strip())
    code_blocks = re.findall(r"```(?:python|py)?\s*(.*?)```", normalized, re.DOTALL | re.IGNORECASE)
    if code_blocks:
        return _unescape_newlines_outside_strings(code_blocks[-1].strip())
    return _unescape_newlines_outside_strings(normalized.strip())


class CodeTwinsFieldTextFormatter(TwinsFieldTextFormatter):
    """
    A `TwinsFieldTextFormatter` that additionally extracts python code for selected fields.

    Default behavior extracts code for the `"solution"` field only, matching the
    common pattern where solver outputs code wrapped in ```python fences.
    """

    def __init__(self, *, code_field_names: set[str] | None = None):
        super().__init__()
        self._code_field_names = set(code_field_names) if code_field_names is not None else {"solution"}

    def format(self, message: str) -> dict:  # type: ignore[override]
        parsed = super().format(message)
        for key in self._code_field_names:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                parsed[key] = _extract_python_code(value)
        return parsed
