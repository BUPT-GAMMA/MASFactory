from __future__ import annotations

import ast
import json
import re

from .base import StatelessFormatter

class LenientJsonMessageFormatter(StatelessFormatter):
    """Best-effort JSON formatter tolerant to fenced blocks and noisy text."""

    def __init__(self):
        super().__init__()
        self._is_input_formatter = True
        self._is_output_formatter = True
        self._agent_introducer = """
        !IMPORTANT!:Your response must contain a single JSON object. Avoid extra text. If you must, wrap the JSON in a ```json code block.
        """

    def format(self, message: str) -> dict:  # type: ignore[override]
        """Parse one JSON object from possibly noisy model output."""
        # Remove <think>...</think> tags and their content.
        if isinstance(message, str):
            message = re.sub(r"<think>.*?</think>", "", message, flags=re.DOTALL).strip()

        if isinstance(message, dict):
            return message

        if not isinstance(message, str):
            message = str(message)

        candidates: list[str] = []

        # Prefer fenced JSON blocks when present.
        for m in re.finditer(r"```(?:json)?\s*(.*?)```", message, flags=re.DOTALL | re.IGNORECASE):
            inner = (m.group(1) or "").strip()
            if inner:
                candidates.append(inner)

        # Fallback: take the widest {...} span.
        start = message.find("{")
        end = message.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(message[start : end + 1].strip())

        # Last resort: try the whole message.
        candidates.append(message.strip())

        last_error: Exception | None = None
        for cand in candidates:
            if not cand:
                continue
            try:
                parsed = json.loads(cand)
            except Exception as e:
                last_error = e
                try:
                    parsed = ast.literal_eval(cand)
                except Exception as e2:
                    last_error = e2
                    continue
            if isinstance(parsed, dict):
                return parsed

        raise ValueError(f"LenientJsonMessageFormatter: failed to parse JSON object: {last_error}")

    def dump(self, message: dict) -> str:
        return json.dumps(message, ensure_ascii=False)

class JsonMessageFormatter(StatelessFormatter):
    """Strict JSON formatter with guarded fallbacks for malformed outputs."""

    def __init__(self):
        super().__init__()
        self._is_input_formatter = True
        self._is_output_formatter = True
        self._agent_introducer = """
        !IMPORTANT!:Your response must strictly and only contain a single JSON object that conforms to the description below. Do not add any extra explanations, comments, or any non-JSON text before or after the JSON code block.
        Your response must be strictly valid JSON. Do not include any Markdown code block markers (e.g., ```json ... ```) or any explanatory text. Ensure all brackets and braces are correctly balanced and matched.
        """

    def _extract_data_with_validation(self, data: dict) -> dict:
        """Normalize parsed JSON object before returning it."""

        def _recursive_extract(data: dict, current_path: list, missing_keys: list) -> dict:

            result = {}

            for key, data_value in data.items():
                new_path = current_path + [key]

                if isinstance(data_value, dict):
                    nested_result = _recursive_extract(
                        data=data_value,
                        current_path=new_path,
                        missing_keys=missing_keys,
                    )
                    if nested_result:
                        result[key] = nested_result
                else:
                    result[key] = data_value

            return result

        missing_keys = []
        result = _recursive_extract(data, current_path=[], missing_keys=missing_keys)

        if missing_keys:
            error_message = f"Data validation failed. Missing required keys: {', '.join(missing_keys)}"
            raise KeyError(error_message)

        return result

    def _strip_code_fences(self, message: str) -> str:
        """Remove outer markdown fences from a candidate string."""
        content = message.strip()
        if content.startswith("```"):
            end_pos = content.rfind("```")
            if end_pos != -1 and end_pos > 3:
                first_newline = content.find("\n")
                if first_newline != -1 and first_newline < end_pos:
                    content = content[first_newline + 1 : end_pos].strip()
        return content

    def _extract_json_substring(self, message: str) -> str:
        """Extract widest `{...}` span from free-form text."""
        content = message.strip()
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            return content[start : end + 1]
        return content

    def _remove_trailing_commas(self, message: str) -> str:
        """Remove trailing commas before `}` or `]`."""
        content = message
        while True:
            updated = re.sub(r",\s*([}\]])", r"\1", content)
            if updated == content:
                return content
            content = updated

    def _balance_brackets(self, message: str) -> str:
        """Append missing closing brackets/braces when detectable."""
        content = message.rstrip()
        stack: list[str] = []
        in_string = False
        escape = False

        for ch in content:
            if escape:
                escape = False
                continue

            if ch == "\\" and in_string:
                escape = True
                continue

            if ch == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if ch == "{" or ch == "[":
                stack.append(ch)
            elif ch == "}" and stack and stack[-1] == "{":
                stack.pop()
            elif ch == "]" and stack and stack[-1] == "[":
                stack.pop()

        if not stack:
            return content

        closing = []
        for opener in reversed(stack):
            closing.append("}" if opener == "{" else "]")
        return content + "".join(closing)

    def _escape_control_chars_in_strings(self, message: str) -> str:
        """Escape raw control chars found inside JSON strings."""
        result_chars: list[str] = []
        in_string = False
        escape = False
        for ch in message:
            if escape:
                result_chars.append(ch)
                escape = False
                continue

            if ch == "\\":
                result_chars.append(ch)
                escape = True
                continue

            if ch == '"':
                result_chars.append(ch)
                in_string = not in_string
                continue

            if in_string:
                if ch == "\n":
                    result_chars.append("\\n")
                    continue
                if ch == "\r":
                    result_chars.append("\\r")
                    continue
                if ch == "\t":
                    result_chars.append("\\t")
                    continue

            result_chars.append(ch)

        return "".join(result_chars)

    def _load_json_with_fallback(self, message: str) -> dict:
        """Try multiple parsing variants and return first JSON object."""
        candidates: list[str] = []

        stripped = message.strip()
        if stripped:
            candidates.append(stripped)

        fence_stripped = self._strip_code_fences(stripped)
        if fence_stripped and fence_stripped not in candidates:
            candidates.append(fence_stripped)

        extracted = self._extract_json_substring(fence_stripped)
        if extracted and extracted not in candidates:
            candidates.append(extracted)

        last_error: Exception | None = None
        for cand in candidates:
            cleaned = self._remove_trailing_commas(cand)
            escaped = self._escape_control_chars_in_strings(cleaned)
            balanced = self._balance_brackets(escaped)
            for variant in (
                cand,
                cleaned,
                escaped,
                balanced,
            ):
                try:
                    parsed = json.loads(variant)
                    if isinstance(parsed, dict):
                        return parsed
                    raise ValueError(f"JSON root must be an object, got {type(parsed).__name__}")
                except Exception as e:
                    last_error = e

                try:
                    decoder = json.JSONDecoder()
                    parsed, _ = decoder.raw_decode(variant)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception as e:
                    last_error = e

        if last_error:
            raise last_error
        raise ValueError("Empty JSON message")

    def format(self, message: str) -> dict:
        """Parse model output into validated JSON object."""

        if isinstance(message, str):
            message = re.sub(r"<think>.*?</think>", "", message, flags=re.DOTALL)

        if isinstance(message, dict):
            return self._extract_data_with_validation(message)

        try:
            parsed = self._load_json_with_fallback(message)
            return self._extract_data_with_validation(parsed)
        except Exception as e:
            if isinstance(e, json.JSONDecodeError):
                print("JSONDecodeError:", e.msg)
            else:
                print("JSONDecodeError:", str(e))
            print("message:", message)
            raise ValueError(f"JSONDecodeError: {str(e)}\nraw message: {message}")

    def dump(self, message: dict) -> str:
        return json.dumps(message)
