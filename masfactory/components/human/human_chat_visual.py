from __future__ import annotations

from masfactory.core.message import ParagraphMessageFormatter
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook
from masfactory.components.human.human_chat import HumanChat


class HumanChatVisual(HumanChat):
    """
    Human-in-the-loop node that prefers interacting via MASFactory Visualizer (VS Code),
    and falls back to CLI input (HumanChat) when Visualizer is unavailable.

    Output fields = output_keys ∪ push_keys (computed at build time).

    Args:
        name (str): Node name.
        pull_keys (dict[str,str] | None): Keys pulled from parent graph attributes.
        push_keys (dict[str,str] | None): Keys pushed back to parent graph attributes.
        attributes (dict[str,object] | None): Initial attributes.
        connect_timeout_s (float): How long to wait for Visualizer connection before falling back to CLI.
    """

    def __init__(
        self,
        name: str,
        pull_keys: dict[str, dict | str] | None = None,
        push_keys: dict[str, dict | str] | None = None,
        attributes: dict[str, object] | None = None,
        *,
        connect_timeout_s: float = 2.0,
    ):
        """Create a HumanChatVisual node.

        Args:
            name: Node name.
            pull_keys: Attribute pull rule for this node.
            push_keys: Attribute push rule for this node.
            attributes: Optional default attributes local to this node.
            connect_timeout_s: Connection timeout for the Visualizer before falling back to CLI.
        """
        super().__init__(name, pull_keys, push_keys, attributes)
        self._connect_timeout_s = float(connect_timeout_s) if connect_timeout_s is not None else 2.0

    def _truncate(self, text: str, max_chars: int = 4500) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "…(truncated)"

    @masf_hook(Node.Hook.FORWARD)
    def _forward(self, input: dict[str, object]):
        """Request user input via Visualizer UI, falling back to CLI if needed."""
        visualizer = None
        try:
            from masfactory.visualizer import connect

            visualizer = connect(timeout_s=max(0.1, self._connect_timeout_s))
        except Exception:
            visualizer = None

        # Fallback to standard HumanChat if Visualizer is not available
        if visualizer is None:
            return super()._forward(input)

        # Use Visualizer for interaction
        formatted_input = self._in_formatter.dump(input)
        output: dict[str, object] = {}
        total_fields = len(self._output_keys)

        for idx, (key, description) in enumerate(self._output_keys.items(), 1):
            header = (
                f"[{self._name}] Human input required ({idx}/{total_fields})\n"
                f"Field: {key}\n"
                f"Description: {description}\n"
            )
            prompt = (
                header
                + "\nContext (incoming message):\n"
                + self._truncate(formatted_input)
                + "\n\nPlease reply with the content for this field.\n"
                + "Tip: You can paste multi-line text."
            )

            resp = None
            try:
                resp = visualizer.request_user_input(
                    node=self._name,
                    prompt=prompt,
                    field=key,
                    description=description,
                    timeout_s=None,
                    meta={"fieldIndex": idx, "fieldTotal": total_fields},
                )
            except Exception:
                resp = None

            if resp is not None:
                output[key] = resp if isinstance(resp, str) else str(resp)
            else:
                # Visualizer was expected but failed mid-flight -> degrade for this field.
                print("=" * 50)
                print(
                    f"[{self._name}] MASFactory Visualizer interaction failed; falling back to CLI for '{key}'."
                )
                print("=" * 50)
                
                # Fallback to inherited method for single input
                print("-" * 50)
                print(f"[Field {idx}/{total_fields}] {key}")
                print(f"Description: {description}")
                print("-" * 50)
                output[key] = self._collect_single_input(f"Please input content for '{key}':")

        return output
