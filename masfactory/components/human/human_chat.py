from __future__ import annotations
import inspect
from typing import Callable, Union
from masfactory.adapters.memory import Memory
from masfactory.core.node import Node
from masfactory.adapters.retrieval import Retrieval
from masfactory.utils.hook import masf_hook
from masfactory.core.message import ParagraphMessageFormatter

class HumanChat(Node):
    """
    Human-in-the-loop node for CLI text input.

    Output fields are computed as `output_keys ∪ push_keys`.
    """
    def __init__(self,
            name,
            pull_keys: dict[str, dict|str] | None = None,
            push_keys: dict[str, dict|str] | None = None,
            attributes: dict[str, object] | None = None):
        """Create a HumanChat node.

        Args:
            name: Node name.
            pull_keys: Attribute pull rule for this node.
            push_keys: Attribute push rule for this node.
            attributes: Optional default attributes local to this node.
        """
        self._in_formatter = ParagraphMessageFormatter()
        # Computed at build time.
        self._output_keys = {}
        super().__init__(name, pull_keys, push_keys, attributes)
    
    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Compute `_output_keys` as `output_keys ∪ push_keys`."""
        self._output_keys = {}
        if self.output_keys:
            self._output_keys.update(self.output_keys)
        if self._push_keys:
            self._output_keys.update(self._push_keys)
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
    
    @masf_hook(Node.Hook.FORWARD)
    def _forward(self, input: dict[str, object]):
        """
        Run one human interaction round.

        Args:
            input: Incoming message.
        Returns:
            dict[str,object]: User-provided output fields.
        """
        formatted_input = self._in_formatter.dump(input)
        print("=" * 50)
        print(f"[{self._name}] Received message:")
        print(formatted_input)
        print("=" * 50)
        
        output = {}
        
        total_fields = len(self._output_keys)
        for idx, (key, description) in enumerate(self._output_keys.items(), 1):
            print("-" * 50)
            print(f"[Field {idx}/{total_fields}] {key}")
            print(f"Description: {description}")
            print("-" * 50)
            user_input = self._collect_single_input(f"Please input content for '{key}':")
            output[key] = user_input
        
        print("=" * 50)
        print(f"[{self._name}] User input completed")
        print("=" * 50)
        
        return output
