from __future__ import annotations

from typing import Generic, TypeVar

from masfactory.core.edge import Edge
from masfactory.core.gate import Gate
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook

ConditionType = TypeVar("ConditionType")


class BaseSwitch(Node, Generic[ConditionType]):
    """Base class for routing switches.

    A switch routes a message to selected out edges, and *closes* non-selected
    edges to avoid downstream nodes being blocked by open-but-unsent in-edges.
    
    Generic parameter T represents the type of condition used for routing.
    Subclasses should specify T to document the condition type.
    """

    def __init__(
        self,
        name: str,
        pull_keys: dict[str, dict|str] | None = None,
        push_keys: dict[str, dict|str] | None = None,
        attributes: dict[str, object] | None = None,
        routes: dict[str, ConditionType] | None = None,
    ):
        """Create a routing switch node.

        Args:
            name: Node name.
            pull_keys: Attribute pull rule for this node.
            push_keys: Attribute push rule for this node.
            attributes: Optional default attributes local to this node.
            routes: Optional declarative routing rules as `receiver_node_name -> condition`.
                These are compiled into edge bindings during `build()`.
        """
        super().__init__(name=name, pull_keys=pull_keys, push_keys=push_keys, attributes=attributes)
        self._condition_edge_branches: dict[Edge, ConditionType] = {}
        # Build-time declarative routing rules: receiver_node_name -> condition.
        # Compiled into _condition_edge_branches during build().
        self._routes: dict[str, ConditionType] | None = routes

    def condition_binding(self, condition: ConditionType, out_edge: Edge) -> None:
        """Bind an out edge to a routing condition."""
        if out_edge in self._condition_edge_branches:
            raise ValueError(f"Edge {out_edge} already bound to a condition")
        if out_edge not in self.out_edges:
            raise ValueError(f"Edge {out_edge} not in {self.name}'s out_edges")
        self._condition_edge_branches[out_edge] = condition

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Compile declarative `routes` into edge condition bindings.

        When `routes` are provided, this validates that each outgoing edge receiver has exactly
        one routing condition and then stores the bindings in `_condition_edge_branches`.
        """
        if self._routes is not None:
            out_edges_by_receiver: dict[str, Edge] = {}
            for edge in self.out_edges:
                receiver_name = edge._receiver.name
                if receiver_name in out_edges_by_receiver:
                    raise ValueError(
                        f"{self.name}: duplicate out edge receiver '{receiver_name}' detected"
                    )
                out_edges_by_receiver[receiver_name] = edge

            unknown = [n for n in self._routes.keys() if n not in out_edges_by_receiver]
            if unknown:
                raise ValueError(
                    f"{self.name}: routes reference unknown receiver node names: {unknown}"
                )

            missing = [n for n in out_edges_by_receiver.keys() if n not in self._routes]
            if missing:
                raise ValueError(
                    f"{self.name}: missing routes for receiver node names: {missing}"
                )

            for receiver_name, condition in self._routes.items():
                self.condition_binding(condition, out_edges_by_receiver[receiver_name])

            # No need to keep the declarative routes after compilation.
            self._routes = None

        self._is_built = True

    @masf_hook(Node.Hook.FORWARD)
    def _forward(self, input: dict[str, object]) -> dict[str, object]:
        return input.copy()

    @masf_hook(Node.Hook.MESSAGE_DISPATCH_OUT)
    def _message_dispatch_out(self, message: dict[str, object]):
        if not self._condition_edge_branches:
            super()._message_dispatch_out(message)
            return

        route_table: dict[Edge, bool] = {}
        for out_edge, condition in self._condition_edge_branches.items():
            route_table[out_edge] = bool(self._evaluate_condition(condition, message))

        for out_edge in self.out_edges:
            if route_table.get(out_edge, False):
                out_edge.send_message(message)
            else:
                out_edge.close()

        self._gate = Gate.OPEN

    def _evaluate_condition(self, condition: ConditionType, message: dict[str, object]) -> bool:
        raise NotImplementedError
