from __future__ import annotations

from .base import StatefulFormatter


class TwinsFieldTextFormatter(StatefulFormatter):
    """
    Copy the raw LLM output to every required output field.

    This formatter intentionally does NOT attempt to parse, normalize, or extract any structure
    from the model output. Whatever the model returns will be stored verbatim under each field key.
    """

    def __init__(self):
        super().__init__()
        self._is_input_formatter = True
        self._is_output_formatter = True
        self._agent_introducer = "Output strictly according to the user's requirements."

    def set_field_keys(self, field_keys: dict[str, str] | None) -> None:  # type: ignore[override]
        """Set the required output field keys for fan-out formatting.

        Args:
            field_keys: Mapping of output field name -> description. When None, clears the
                current schema.
        """
        super().set_field_keys(field_keys)

    def format(self, message: object) -> dict:  # type: ignore[override]
        self._require_field_keys_set()
        if not self._field_keys:
            return {}
        return {k: message for k in self._field_keys.keys()}

    def dump(self, message: dict) -> str:  # type: ignore[override]
        if not isinstance(message, dict):
            return str(message)
        parts: list[str] = []
        for k, v in message.items():
            parts.append(f"{k}:\n{v}")
        return "\n\n".join(parts)
