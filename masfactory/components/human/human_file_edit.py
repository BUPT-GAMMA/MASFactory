from __future__ import annotations
import ast
import dataclasses
import inspect
import json
import os
import pprint
from typing import Callable, Union
from masfactory.adapters.memory import Memory
from masfactory.core.node import Node
from masfactory.adapters.retrieval import Retrieval
from masfactory.utils.hook import masf_hook
from masfactory.core.message import ParagraphMessageFormatter

class HumanFileEdit(Node):
    """
    Human node that combines file editing and CLI chat input.

    Output fields are split into:
    - file fields: values written to files and read back after editing.
    - chat fields: values collected from CLI text input.
    """
    def __init__(self,
            name,
            file_fields: dict[str, str] | None = None,
            pull_keys: dict[str, dict|str] | None = None,
            push_keys: dict[str, dict|str] | None = None,
            attributes: dict[str, object] | None = None):
        """Create a HumanFileEdit node.

        Args:
            name: Node name.
            file_fields: Mapping of output field name -> file path. These fields are written to disk,
                the user edits the file, and the edited content is read back.
            pull_keys: Attribute pull rule for this node.
            push_keys: Attribute push rule for this node.
            attributes: Optional default attributes local to this node.
        """
        self._in_formatter = ParagraphMessageFormatter()

        # Mapping: field key -> file path
        self._file_fields = file_fields if file_fields is not None else {}

        # Computed at build time: all output fields minus file fields
        self._chat_fields = {}
        
        super().__init__(name, pull_keys, push_keys, attributes)
    
    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Compute chat fields as `(output_keys ∪ push_keys) - file_fields`."""
        all_output_keys = {}
        if self.output_keys:
            all_output_keys.update(self.output_keys)
        if self._push_keys:
            all_output_keys.update(self._push_keys)
        
        self._chat_fields = {
            key: desc 
            for key, desc in all_output_keys.items() 
            if key not in self._file_fields
        }
        
        super().build()
    
    def _collect_single_input(self, prompt: str = None) -> str:
        """Collect multiline CLI input for one field."""
        if prompt:
            print(prompt)
        print("When finished, type '$END' on a new line to submit:")
        user_input_lines = []
        while True:
            line = input()
            if line.strip() == "$END":
                break
            user_input_lines.append(line)
        return "\n".join(user_input_lines)

    def _to_jsonable(self, value: object) -> object | None:
        if dataclasses.is_dataclass(value):
            try:
                return dataclasses.asdict(value)
            except Exception:
                return None

        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump()
                if isinstance(dumped, dict):
                    return dumped
            except Exception:
                pass

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                dumped = to_dict()
                if isinstance(dumped, dict):
                    return dumped
            except Exception:
                pass

        obj_dict = getattr(value, "__dict__", None)
        if isinstance(obj_dict, dict):
            try:
                return {k: v for k, v in obj_dict.items() if not callable(v)}
            except Exception:
                return None

        return None

    def _json_default(self, value: object):
        if isinstance(value, (set, tuple)):
            return list(value)
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode("utf-8", errors="replace")
        jsonable = self._to_jsonable(value)
        if jsonable is not None:
            return jsonable
        return str(value)

    def _serialize_field_value(self, content: object) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            stripped = content.strip()
            if stripped and (
                (stripped.startswith("{") and stripped.endswith("}"))
                or (stripped.startswith("[") and stripped.endswith("]"))
            ):
                parsed = None
                try:
                    parsed = json.loads(stripped)
                except Exception:
                    try:
                        parsed = ast.literal_eval(stripped)
                    except Exception:
                        parsed = None
                if isinstance(parsed, (dict, list, tuple, set)):
                    try:
                        return json.dumps(
                            parsed,
                            ensure_ascii=False,
                            indent=2,
                            default=self._json_default,
                        )
                    except Exception:
                        # Fall back to the original string.
                        return content
            return content
        if isinstance(content, (bytes, bytearray)):
            return bytes(content).decode("utf-8", errors="replace")

        if isinstance(content, (dict, list, tuple, set)):
            try:
                return json.dumps(content, ensure_ascii=False, indent=2, default=self._json_default)
            except Exception:
                return pprint.pformat(content, width=120, compact=False)

        jsonable = self._to_jsonable(content)
        if jsonable is not None:
            try:
                return json.dumps(jsonable, ensure_ascii=False, indent=2, default=self._json_default)
            except Exception:
                return pprint.pformat(jsonable, width=120, compact=False)

        return str(content)

    def _write_raw_file(self, file_path: str, text: str) -> None:
        dir_path = os.path.dirname(file_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text)

    def _read_raw_file(self, file_path: str) -> str:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    
    def _write_file_field(self, field_name: str, file_path: str, content: object) -> bool:
        """Write one file field to disk."""
        try:
            print(f"\nSaving '{field_name}' to file: {file_path}")
            self._write_raw_file(file_path, self._serialize_field_value(content))
            return True
        except Exception as e:
            print(f"Failed to write file: {e}")
            return False

    def _read_file_field(self, field_name: str, file_path: str) -> str:
        """Read one file field from disk."""
        try:
            file_content = self._read_raw_file(file_path)
            print(f"Read file field '{field_name}' (length={len(file_content)} chars)")
            return file_content
        except Exception as e:
            print(f"Failed to read file: {e}")
            return ""

    def _wait_for_file_edit_confirmation(self):
        """Block until user confirms file edits are done."""
        print("Files are ready. Please edit them in your editor, then type '$END' and press Enter to continue:")
        while True:
            line = input()
            if line.strip() == "$END":
                break

    @masf_hook(Node.Hook.FORWARD)
    def _forward(self, input_dict: dict[str, object]):
        """
        Run one file-edit + chat interaction round.

        Args:
            input_dict: Incoming message.
        Returns:
            dict[str,object]: Output collected from files and chat fields.
        """
        formatted_input = self._in_formatter.dump(input_dict)
        print("=" * 50)
        print(f"[{self._name}] Received message:")
        print(formatted_input)
        print("=" * 50)
        
        output = {}
        total_fields = len(self._file_fields) + len(self._chat_fields)
        current_field = 0
        
        # 1) Write file fields.
        for field_name, file_path in self._file_fields.items():
            current_field += 1
            print("-" * 50)
            print(f"[File Edit {current_field}/{total_fields}] {field_name} -> {file_path}")
            print("-" * 50)
            
            content = input_dict.get(field_name, "")
            self._write_file_field(field_name, file_path, content)
            print(f"File saved. Please edit: {file_path}")

        # 2. Wait for the user to finish editing files before reading them back.
        # This keeps the interaction deterministic and avoids reading stale content.
        if self._file_fields:
            self._wait_for_file_edit_confirmation()
        
        # 3) Read file fields.
        for field_name, file_path in self._file_fields.items():
             file_content = self._read_file_field(field_name, file_path)
             output[field_name] = file_content

        # 4) Collect chat fields.
        for field_name, description in self._chat_fields.items():
            current_field += 1
            print("-" * 50)
            print(f"[Chat Input {current_field}/{total_fields}] {field_name}")
            print(f"Description: {description}")
            print("-" * 50)
            user_input = self._collect_single_input(
                f"Please input content for '{field_name}':\n(Make sure the file edits above are completed first.)"
            )
            output[field_name] = user_input
        
        print("=" * 50)
        print(f"[{self._name}] Human interaction completed")
        print("=" * 50)
        
        return output
