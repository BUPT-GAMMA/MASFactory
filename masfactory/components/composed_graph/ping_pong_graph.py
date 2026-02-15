from __future__ import annotations
from typing import Callable
from masfactory.components.graphs.loop import Loop
from masfactory.components.controls.logic_switch import LogicSwitch
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook


class PingPongGraph(Loop):
    """A two-node alternating loop ("ping-pong") graph.

    Topology:
    - CONTROLLER -> switch
    - switch -> node_a / node_b (alternating by iteration)
    - node_a -> CONTROLLER
    - node_b -> CONTROLLER
    """
    
    def __init__(
        self,
        name: str,
        node_a: dict,
        node_b: dict,
        node_a_in_keys: dict[str, str] = None,
        node_a_out_keys: dict[str, str] = None,
        node_b_in_keys: dict[str, str] = None,
        node_b_out_keys: dict[str, str] = None,
        node_a_first: bool = True,
        max_turns: int = 20,
        terminate_condition_function: Callable | None = None,
        terminate_condition_prompt: str | None = None,
        pull_keys: dict[str, dict|str] | None = None,
        push_keys: dict[str, dict|str] | None = None,
        attributes: dict[str, object] | None = None
    ):
        """Create a PingPongGraph.

        Args:
            name: Graph name.
            node_a: `create_node(...)` kwargs for node A. Must include the target class under
                `cls` (or equivalent field expected by `create_node`).
            node_b: `create_node(...)` kwargs for node B. Must include the target class under
                `cls` (or equivalent field expected by `create_node`).
            node_a_in_keys: Edge keys from switch -> node A. When None, best-effort inferred
                from `node_b_out_keys` (or `{}` as fallback).
            node_a_out_keys: Edge keys from node A -> controller. When None, best-effort inferred
                from `node_b_in_keys` (or `{}` as fallback).
            node_b_in_keys: Edge keys from switch -> node B. When None, best-effort inferred
                from `node_a_out_keys` (or `{}` as fallback).
            node_b_out_keys: Edge keys from node B -> controller. When None, best-effort inferred
                from `node_a_in_keys` (or `{}` as fallback).
            node_a_first: If True, node A acts first; otherwise node B acts first.
            max_turns: Maximum number of loop iterations.
            terminate_condition_function: Optional early-termination predicate.
                Signature: `(message: dict, attributes: dict) -> bool`.
            terminate_condition_prompt: Optional LLM prompt used for termination checks when
                supported by the Loop implementation.
            pull_keys: Attribute pull rule for this loop graph.
            push_keys: Attribute push rule for this loop graph.
            attributes: Default attributes for this loop graph.
        """
        super().__init__(
            name=name,
            pull_keys=pull_keys,
            push_keys=push_keys,
            max_iterations=max_turns,
            terminate_condition_function=terminate_condition_function,
            terminate_condition_prompt=terminate_condition_prompt,
            attributes=attributes
        )
        
        self._node_a_config = node_a
        self._node_b_config = node_b
        
        self._node_a_in_keys = node_a_in_keys if node_a_in_keys else node_b_out_keys if node_b_out_keys else {}
        self._node_a_out_keys = node_a_out_keys if node_a_out_keys else node_b_in_keys if node_b_in_keys else {}
        self._node_b_in_keys = node_b_in_keys if node_b_in_keys else node_a_out_keys if node_a_out_keys else {}
        self._node_b_out_keys = node_b_out_keys if node_b_out_keys else node_a_in_keys if node_a_in_keys else {}
        
        self._node_a_first = node_a_first
        
        self._node_a: Node = None
        self._node_b: Node = None
        self._switch: LogicSwitch = None
    
    @property
    def node_a(self) -> Node:
        """Return node A (available after build)."""
        return self._node_a
    
    @property
    def node_b(self) -> Node:
        """Return node B (available after build)."""
        return self._node_b
    
    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build the internal topology for alternating node execution."""
        self._node_a = self.create_node(
            **self._node_a_config
        )
        
        self._node_b = self.create_node(
            **self._node_b_config
        )
        
        self._switch = self.create_node(
            LogicSwitch,
            name=f"{self.name}_switch",
        )
        
        all_keys = {**self._node_a_in_keys, **self._node_b_in_keys}
        self.edge_from_controller(
            receiver=self._switch,
            keys=all_keys
        )
        
        edge_to_a = self.create_edge(
            sender=self._switch,
            receiver=self._node_a,
            keys=self._node_a_in_keys
        )
        
        edge_to_b = self.create_edge(
            sender=self._switch,
            receiver=self._node_b,
            keys=self._node_b_in_keys
        )
        
        self.edge_to_controller(
            sender=self._node_a,
            keys=self._node_a_out_keys
        )
        
        self.edge_to_controller(
            sender=self._node_b,
            keys=self._node_b_out_keys
        )
        
        def switch_to_a(message: dict, attributes: dict) -> bool:
            current_iteration = attributes.get("current_iteration", 0)
            if self._node_a_first:
                return current_iteration % 2 == 1
            else:
                return current_iteration % 2 == 0
        
        def switch_to_b(message: dict, attributes: dict) -> bool:
            current_iteration = attributes.get("current_iteration", 0)
            if self._node_a_first:
                return current_iteration % 2 == 0
            else:
                return current_iteration % 2 == 1
        
        self._switch.condition_binding(switch_to_a, edge_to_a)
        self._switch.condition_binding(switch_to_b, edge_to_b)
        
        super().build()
