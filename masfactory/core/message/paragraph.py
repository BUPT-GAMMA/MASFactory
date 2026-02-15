from __future__ import annotations

from .base import StatelessFormatter

class ParagraphMessageFormatter(StatelessFormatter):
    """Formatter for `KEY:\\nvalue` paragraph-style message payloads."""

    def __init__(self):
        super().__init__()
        self._is_input_formatter = True
        self._is_output_formatter = True
        self._agent_introducer = """
        Your response must strictly and only follow the format below.
        1. Your response is a collection of key-value pairs.
        2. For each key-value pair, the key firstly comes and then follows a colon and then the next line follows the value.
        3. A key must write in one line and must not contain any newline.
        4. A value can contain multiple lines and end with ".".
        FORMAT EXAMPLE:
        KEY1:
        value1
        KEY2:
        value2
        KEY3:
        value3
        ...
        """

    def format(self, message: str) -> dict:
        """Parse paragraph text into key-value dictionary."""

        if isinstance(message, dict):
            return message

        result = {}
        lines = message.split("\n")
        current_key = None
        current_content = []

        for line in lines:
            line = line.rstrip()
            if ":" in line and not line.startswith(" "):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    if current_key is not None and current_content:
                        content = "\n".join(current_content).strip()
                        if current_key in result:
                            result[current_key] += "\n" + content
                        else:
                            result[current_key] = content

                    current_key = parts[0].strip()
                    current_content = [parts[1].strip()] if parts[1].strip() else []
            elif current_key is not None:
                current_content.append(line)

        if current_key is not None and current_content:
            content = "\n".join(current_content).strip()
            if current_key in result:
                result[current_key] += "\n" + content
            else:
                result[current_key] = content

        return result

    def dump(self, message: dict) -> str:
        """Serialize key-value dictionary to paragraph text."""

        if isinstance(message, str):
            return message

        def _indent_block(text: str) -> str:
            if not text:
                return ""
            return "\n".join(f" {line}" for line in text.splitlines())

        result_lines: list[str] = []
        for key, value in message.items():
            result_lines.append(f"{key}:")
            if value is not None:
                if isinstance(value, str):
                    rendered = value
                else:
                    rendered = _indent_block(self.render_value(value))
                result_lines.append(rendered)

        return "\n".join(result_lines).strip()
