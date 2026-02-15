"""CAMEL message formatter for handling natural language output.

This module provides the CamelMessageFormatter class, which extends the base
MessageFormatter to handle natural language responses from CAMEL role-playing agents.
"""

from masfactory.core.message import MessageFormatter
import json
import re


class CamelMessageFormatter(MessageFormatter):
    """Message formatter for CAMEL role-playing, supporting natural language output.
    
    This formatter is designed to handle flexible output formats from agents,
    including JSON, natural language, and mixed formats.
    """
    
    def __init__(self, output_key: str = "message", required_keys: set[str] | list[str] | None = None):
        super().__init__()
        self._is_input_formatter = True
        self._is_output_formatter = True
        self._output_key = output_key
        if required_keys is None:
            self._required_keys = set()
        elif isinstance(required_keys, list):
            self._required_keys = set(required_keys)
        else:
            self._required_keys = required_keys
        self._agent_introducer = f"""
        Your response will be used as the value for the key "{output_key}".
        Please provide your response naturally, without any JSON formatting.
        Your response should be clear and complete.
        """
    
    def _fill_required_keys(self, result: dict, formatter_value: str) -> dict:
        """Fill all required keys in the result dictionary."""
        if self._required_keys:
            for key in self._required_keys:
                if key not in result:
                    result[key] = formatter_value
        return result
    
    def format(self, message: str) -> dict:
        """Format message string into dictionary format."""
        cleaned_message = message.strip() if isinstance(message, str) else str(message).strip()
        if isinstance(message, dict):
            if self._output_key in message:
                formatter_value = message[self._output_key]
                return self._fill_required_keys(message.copy(), formatter_value)
            if len(message) == 1:
                result = {self._output_key: list(message.values())[0]}
                return self._fill_required_keys(result, result[self._output_key])
            result = {self._output_key: str(message)}
            return self._fill_required_keys(result, result[self._output_key])
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', cleaned_message, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                if isinstance(parsed, dict):
                    if self._output_key in parsed:
                        formatter_value = parsed[self._output_key]
                        return self._fill_required_keys(parsed.copy(), formatter_value)
                    if len(parsed) == 1:
                        result = {self._output_key: list(parsed.values())[0]}
                        return self._fill_required_keys(result, result[self._output_key])
                    result = {self._output_key: str(parsed)}
                    return self._fill_required_keys(result, result[self._output_key])
            except (json.JSONDecodeError, ValueError):
                pass
        try:
            parsed = json.loads(cleaned_message)
            if isinstance(parsed, dict):
                if self._output_key in parsed:
                    formatter_value = parsed[self._output_key]
                    return self._fill_required_keys(parsed.copy(), formatter_value)
                if len(parsed) == 1:
                    result = {self._output_key: list(parsed.values())[0]}
                    return self._fill_required_keys(result, result[self._output_key])
                result = {self._output_key: str(parsed)}
                return self._fill_required_keys(result, result[self._output_key])
        except (json.JSONDecodeError, ValueError):
            pass
        result = {self._output_key: cleaned_message}
        return self._fill_required_keys(result, cleaned_message)
    
    def dump(self, message: dict) -> str:
        """Convert dictionary to string format."""
        if isinstance(message, str):
            return message
        if self._output_key in message:
            return str(message[self._output_key])
        if "MESSAGE TO YOU" in message:
            return str(message["MESSAGE TO YOU"])
        if len(message) == 1:
            return str(list(message.values())[0])
        return str(message)

