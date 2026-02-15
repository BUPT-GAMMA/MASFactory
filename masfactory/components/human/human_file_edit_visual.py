from __future__ import annotations

import os

from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook

from masfactory.components.human.human_file_edit import HumanFileEdit


class HumanFileEditVisual(HumanFileEdit):
    """
    Visual version of HumanFileEdit.

    Prefers interacting via MASFactory Visualizer (VS Code) to preview/edit the target files,
    then blocks on a chat-style confirmation in the Visualizer chat window.

    If Visualizer is unavailable, falls back to CLI behavior (HumanFileEdit).

    Notes:
    - JSON graph_design files are opened in the Visualizer "Vibe" tab (editable).
    - Code files are opened in the Visualizer "Preview" tab (graph preview is read-only);
      the source file itself can still be edited in VS Code.
    """

    def __init__(
        self,
        name: str,
        file_fields: dict[str, str] | None = None,
        pull_keys: dict[str, dict | str] | None = None,
        push_keys: dict[str, dict | str] | None = None,
        attributes: dict[str, object] | None = None,
        *,
        connect_timeout_s: float = 2.0,
    ):
        """Create a HumanFileEditVisual node.

        Args:
            name: Node name.
            file_fields: Mapping of output field name -> file path to open/edit.
            pull_keys: Attribute pull rule for this node.
            push_keys: Attribute push rule for this node.
            attributes: Optional default attributes local to this node.
            connect_timeout_s: Connection timeout for the Visualizer before falling back to CLI.
        """
        super().__init__(
            name=name,
            file_fields=file_fields or {},
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
        )
        self._connect_timeout_s = float(connect_timeout_s) if connect_timeout_s is not None else 2.0

    def _truncate(self, text: str, max_chars: int = 4500) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "…(truncated)"

    def _is_json_file(self, file_path: str) -> bool:
        p = str(file_path or "").lower()
        return p.endswith(".json") or p.endswith(".jsonc")

    @masf_hook(Node.Hook.FORWARD)
    def _forward(self, input_dict: dict[str, object]):
        """Open/edit files via Visualizer, then collect chat fields and return combined output."""
        visualizer = None
        try:
            from masfactory.visualizer import VisualizerOpenFileOptions, connect

            visualizer = connect(timeout_s=max(0.1, self._connect_timeout_s))
        except Exception:
            visualizer = None

        if visualizer is None:
            # Fall back to base CLI behavior.
            return super()._forward(input_dict)

        formatted_input = self._in_formatter.dump(input_dict)
        print("=" * 50)
        print(f"[{self._name}] Received message:")
        print(formatted_input)
        print("=" * 50)

        output: dict[str, object] = {}
        total_fields = len(self._file_fields) + len(self._chat_fields)
        current_field = 0

        # 1) Write and open all files.
        for field_name, raw_path in self._file_fields.items():
            current_field += 1
            file_path = os.path.abspath(str(raw_path))
            content = input_dict.get(field_name, "")

            try:
                self._write_raw_file(file_path, self._serialize_field_value(content))
                ok_write = True
            except Exception:
                ok_write = False
            
            print("-" * 50)
            print(f"[File Edit {current_field}/{total_fields}] {field_name} -> {file_path}")
            print("-" * 50)

            if not ok_write:
                print(f"[{self._name}] Failed to write file for '{field_name}': {file_path}")
            
            view = "vibe" if self._is_json_file(file_path) else "preview"
            try:
                visualizer.open_file(
                    VisualizerOpenFileOptions(
                        file_path=file_path,
                        view=view,  # type: ignore[arg-type]
                        reveal=True,
                        preserve_focus=None,
                    )
                )
            except Exception:
                pass

        # 2) Ask explicit confirmation only when there are no chat fields.
        if self._file_fields and not self._chat_fields:
            prompt = (
                f"[{self._name}] Files opened for editing.\n"
                "Please review/edit the files in VS Code.\n"
                "When finished, reply to this message to continue.\n"
                "\n"
                "Context (incoming message):\n"
                + self._truncate(formatted_input)
            )
            try:
                visualizer.request_user_input(
                    node=self._name,
                    prompt=prompt,
                    field="confirmation",
                    description="Confirm file edits",
                    timeout_s=None,
                    meta={"kind": "confirmation"},
                )
            except Exception:
                print(f"[{self._name}] Visualizer confirmation failed; falling back to CLI wait.")
                self._wait_for_file_edit_confirmation()

        # 3) Read all files.
        for field_name, raw_path in self._file_fields.items():
            file_path = os.path.abspath(str(raw_path))
            try:
                file_content = self._read_raw_file(file_path)
            except Exception:
                output[field_name] = ""
                continue
            output[field_name] = file_content

        # 4) Collect chat fields.
        for field_name, description in self._chat_fields.items():
            current_field += 1
            header = (
                f"[{self._name}] Human input required ({current_field}/{total_fields})\n"
                f"Field: {field_name}\n"
                f"Description: {description}\n"
            )
            # Add a file-edit tip on the first chat field.
            files_tip = ""
            if current_field == len(self._file_fields) + 1 and self._file_fields:
                 files_tip = "\n(Submitting this will also confirm your file edits)\n"

            prompt = (
                header
                + "\nContext (incoming message):\n"
                + self._truncate(formatted_input)
                + files_tip
                + "\n\nPlease reply with the content for this field.\n"
                + "Tip: You can paste multi-line text."
            )

            resp = None
            try:
                resp = visualizer.request_user_input(
                    node=self._name,
                    prompt=prompt,
                    field=field_name,
                    description=str(description),
                    timeout_s=None,
                    meta={"kind": "chat", "fieldIndex": current_field, "fieldTotal": total_fields},
                )
            except Exception:
                resp = None

            if resp is not None:
                output[field_name] = resp
            else:
                # Fall back to CLI for this field.
                print("=" * 50)
                print(
                    f"[{self._name}] MASFactory Visualizer interaction failed; falling back to CLI for '{field_name}'."
                )
                print("=" * 50)
                print("-" * 50)
                print(f"[Chat Input {current_field}/{total_fields}] {field_name}")
                print(f"Description: {description}")
                print("-" * 50)
                output[field_name] = self._collect_single_input(f"Please input content for '{field_name}':")

        return output
