"""Native MASFactory operator dispatch loop."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from masfactory.components.controls.logic_switch import LogicSwitch
from masfactory.components.graphs.loop import Loop

from .components.invalid_operator_node import InvalidOperatorNode
from .components.logic_switch import operator_route
from .components.route_cursor_node import RouteCursorNode
from .components.state_reducer_node import StateReducerNode
from .components.controller_message import LoopControllerMessage
from ..attribute_firewall import seal_loop_attributes
from applications.maas_reproduction.maas_reproduction.schemas import OperatorResult
from applications.maas_reproduction.maas_reproduction.contracts import EARLY_STOP_OPERATOR
from masfactory.components.custom_node import CustomNode


LOOP_CONTROL_KEYS = {"loop_control": "LoopControllerMessage only."}


def should_terminate(message: dict, attributes: dict) -> bool:
    control = message.get("loop_control")
    if not isinstance(control, LoopControllerMessage):
        raise TypeError("loop_control must be a LoopControllerMessage")
    return not control.should_continue


class OperatorDispatchLoop(Loop):
    """Execute registered operators in flattened RoutePlan order."""

    def __init__(
        self,
        name: str = "operator_dispatch_loop",
        *,
        operator_registry: Mapping[str, Mapping[str, Any]] | None = None,
        max_iterations: int = 100,
    ) -> None:
        if isinstance(max_iterations, bool) or max_iterations <= 0:
            raise ValueError("max_iterations must be a positive integer")
        self.operator_registry = dict(operator_registry or {})
        super().__init__(
            name=name,
            max_iterations=max_iterations,
            terminate_condition_function=should_terminate,
            pull_keys={},
            push_keys={"dispatch_state": "Final dispatch state."},
        )
        seal_loop_attributes(self)

    def _forward(self, input: dict[str, object]) -> dict[str, object]:
        """Keep business state out of the internal controller message.

        The parent graph sends the initial ``dispatch_state`` to this composite node.
        It is stored in the Loop-local attribute store, while the controller receives
        only a ``LoopControllerMessage``.
        """
        state = input.get("dispatch_state")
        # Loop.reset_gate() deliberately resets execution gates only. Business
        # state is invocation-local, so remove the previous sample explicitly.
        self._attributes_store.pop("dispatch_state", None)
        if state is None:
            return {
                "dispatch_state": None,
                "failure_source": input.get("failure_source"),
                "error_state": input.get("error_state"),
            }
        self._attributes_store["dispatch_state"] = state
        should_continue = not getattr(state, "termination_requested", False)
        route_plan = getattr(state, "route_plan", None)
        route_cursor = getattr(state, "route_cursor", 0)
        if route_plan is not None:
            should_continue = should_continue and route_cursor < len(route_plan.items)

        super()._forward(
            {
                "loop_control": LoopControllerMessage(
                    cursor=route_cursor,
                    iteration=0,
                    should_continue=should_continue,
                )
            }
        )
        return {
            "dispatch_state": self._attributes_store.get("dispatch_state"),
            "failure_source": input.get("failure_source"),
            "error_state": input.get("error_state"),
        }

    def build(self) -> None:
        if self._is_built:
            return
        cursor = self.create_node(RouteCursorNode, "route_cursor")
        switch = self.create_node(LogicSwitch, "operator_switch", pull_keys={}, push_keys={})
        invalid = self.create_node(InvalidOperatorNode, "invalid_operator")
        early_stop = self.create_node(
            CustomNode,
            "early_stop_control",
            forward=lambda message: {
                "operator_result": OperatorResult(
                    EARLY_STOP_OPERATOR,
                    "control",
                    metadata={"termination_requested": True},
                )
            },
            pull_keys={},
            push_keys={},
        )
        reducer = self.create_node(StateReducerNode, "state_reducer")

        self.edge_from_controller(cursor, keys=LOOP_CONTROL_KEYS)
        self.create_edge(cursor, switch, {"operator_invocation": "Current operator invocation."})

        operator_nodes: dict[str, Any] = {}
        for operator_name, spec in self.operator_registry.items():
            node_class = spec.get("node_class")
            config = dict(spec.get("config") or {})
            if node_class is None:
                raise ValueError(f"operator registry entry {operator_name!r} lacks node_class")
            operator_nodes[operator_name] = self.create_node(node_class, operator_name, **config)
            self.create_edge(
                operator_nodes[operator_name], reducer,
                {"operator_result": "Structured OperatorResult."},
            )
            edge = self.create_edge(
                switch, operator_nodes[operator_name],
                {"operator_invocation": "Current operator invocation."},
            )
            switch.condition_binding(operator_route(operator_name), edge)

        invalid_edge = self.create_edge(
            switch, invalid,
            {"operator_invocation": "Current operator invocation."},
        )
        early_stop_edge = self.create_edge(
            switch,
            early_stop,
            {"operator_invocation": "EarlyStop control marker."},
        )
        switch.condition_binding(
            lambda message, attributes: (
                (message["operator_invocation"].operator_name
                 if hasattr(message["operator_invocation"], "operator_name")
                 else message["operator_invocation"]["operator_name"])
                == EARLY_STOP_OPERATOR
            ),
            early_stop_edge,
        )
        self.create_edge(
            early_stop,
            reducer,
            {"operator_result": "Structured EarlyStop control result."},
        )
        switch.condition_binding(
            lambda message, attributes: (
                (message["operator_invocation"].operator_name
                 if hasattr(message["operator_invocation"], "operator_name")
                 else message["operator_invocation"]["operator_name"])
                not in operator_nodes and (
                    message["operator_invocation"].operator_name
                    if hasattr(message["operator_invocation"], "operator_name")
                    else message["operator_invocation"]["operator_name"]
                ) != EARLY_STOP_OPERATOR
            ),
            invalid_edge,
        )
        self.create_edge(
            invalid, reducer,
            {"operator_result": "Structured OperatorResult."},
        )
        self.edge_to_controller(reducer, keys=LOOP_CONTROL_KEYS)
        super().build()


__all__ = ["LOOP_CONTROL_KEYS", "LoopControllerMessage", "OperatorDispatchLoop", "should_terminate"]
