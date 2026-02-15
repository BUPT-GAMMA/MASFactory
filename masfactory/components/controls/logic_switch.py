from __future__ import annotations

from typing import Callable

from masfactory.components.controls.base_switch import BaseSwitch

class LogicSwitch(BaseSwitch[Callable[[dict, dict[str, object]], bool]]):
    """Switch node that routes by evaluating boolean callables."""

    def __init__(
        self,
        name: str,
        pull_keys: dict[str, dict|str] | None = None,
        push_keys: dict[str, dict|str] | None = None,
        attributes: dict[str, object] | None = None,
        routes: dict[str, Callable[[dict, dict[str, object]], bool]] | None = None,
    ):
        """Create a LogicSwitch.

        Args:
            name: Node name.
            pull_keys: Attribute pull rule for this node.
            push_keys: Attribute push rule for this node.
            attributes: Optional default attributes local to this node.
            routes: Optional declarative routing rules as `receiver_node_name -> predicate`.
        """
        super().__init__(
            name=name,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
            routes=routes,
        )

    def _evaluate_condition(
        self,
        condition: Callable[[dict, dict[str, object]], bool],
        message: dict[str, object],
    ) -> bool:
        return bool(condition(message, self._attributes_store))
