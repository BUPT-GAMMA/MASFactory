"""
HubGraph - Hub-and-spoke composite component using standard masfactory patterns.

This is a composite component (class-based) that creates a hub-and-spoke
multi-agent system using standard Loop + LogicSwitch + Agent.
"""
from __future__ import annotations

from typing import Callable

from masfactory import NodeTemplate, Shared
from masfactory.adapters.memory import HistoryMemory
from masfactory.adapters.model import Model
from masfactory.components.agents.agent import Agent
from masfactory.components.controls.logic_switch import LogicSwitch
from masfactory.components.graphs.loop import Loop
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook


class HubGraph(Loop):
    """Hub-and-spoke composite component with handoff mechanism.

    A composite component that creates a Loop with a central hub agent
    that can delegate to spoke agents via handoff tools.
    """

    def __init__(
        self,
        name: str,
        hub: NodeTemplate,
        spokes: list[NodeTemplate],
        model: Model,
        graph_instructions: str = "",
        max_iterations: int = 20,
        shared_memory: HistoryMemory | None = None,
        handoff_tool_prefix: str = "transfer_to_",
        terminate_condition_function: Callable | None = None,
        pull_keys: dict | None = None,
        push_keys: dict | None = None,
        attributes: dict | None = None,
    ):
        """Create a HubGraph composite component.

        Args:
            name: Name of this hub graph.
            hub: NodeTemplate for the hub agent.
            spokes: List of NodeTemplates for spoke agents.
            model: Model adapter for agents.
            graph_instructions: Shared instructions prepended to all agents.
            max_iterations: Maximum number of loop iterations.
            shared_memory: Optional shared HistoryMemory. Auto-created if None.
            handoff_tool_prefix: Prefix for generated handoff tools.
            terminate_condition_function: Custom termination predicate.
            pull_keys: Attribute pull rule for this loop.
            push_keys: Attribute push rule for this loop.
            attributes: Initial loop attributes.
        """
        self._hub_template = hub
        self._spoke_templates = spokes
        self._model = model
        self._graph_instructions = graph_instructions
        self._handoff_tool_prefix = handoff_tool_prefix
        
        # Create shared memory if not provided
        self._shared_memory = shared_memory or HistoryMemory(top_k=100, memory_size=100)
        
        # Extract names
        self._hub_name = hub.prototype_config.get("role_name", "hub")
        self._spoke_names = [
            tpl.prototype_config.get("role_name", f"spoke_{i}")
            for i, tpl in enumerate(spokes)
        ]
        self._spoke_names_set = set(self._spoke_names)
        
        # Initialize attributes for handoff tracking
        init_attrs = attributes.copy() if attributes else {}
        init_attrs.setdefault("_handoff_to", None)
        init_attrs.setdefault("_last_actor", None)
        
        # Default termination: hub finished without handoff
        if terminate_condition_function is None:
            terminate_condition_function = self._default_terminate_condition
        
        super().__init__(
            name=name,
            max_iterations=max_iterations,
            terminate_condition_function=terminate_condition_function,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=init_attrs,
        )

    def _default_terminate_condition(self, message: dict, attributes: dict) -> bool:
        """Terminate when hub responds without handoff."""
        last = attributes.get("_last_actor")
        handoff = attributes.get("_handoff_to")
        return last == self._hub_name and (handoff is None or handoff == "")

    def _create_handoff_tool(self, spoke_name: str) -> Callable:
        """Create a handoff tool for routing to a spoke."""
        tool_name = f"{self._handoff_tool_prefix}{spoke_name.lower().replace(' ', '_')}"
        
        def transfer_tool(**kwargs) -> str:
            self._attributes_store["_handoff_to"] = spoke_name
            return f"Transferred to {spoke_name}"
        
        transfer_tool.__name__ = tool_name
        transfer_tool.__doc__ = f"Transfer the conversation to {spoke_name} for specialized help."
        return transfer_tool

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build the hub-spoke topology with handoff routing."""
        if self._is_built:
            return

        # Build routing conditions
        routes: dict[str, Callable] = {}
        
        # Hub: route when no handoff pending
        def route_to_hub(message: dict, attributes: dict) -> bool:
            handoff = attributes.get("_handoff_to")
            return handoff is None or handoff == "" or handoff not in self._spoke_names_set
        routes[self._hub_name] = route_to_hub
        
        # Spokes: route when handoff matches
        for spoke_name in self._spoke_names:
            def make_spoke_condition(target: str) -> Callable:
                def condition(message: dict, attributes: dict) -> bool:
                    return attributes.get("_handoff_to") == target
                return condition
            routes[spoke_name] = make_spoke_condition(spoke_name)

        # Create router
        router = self.create_node(
            LogicSwitch,
            name=f"{self.name}_router",
            routes=routes,
        )
        
        # Clear handoff after dispatch
        def clear_handoff(_node: Node, _result: object, _message: dict) -> None:
            self._attributes_store["_handoff_to"] = None
        router.hooks.register(Node.Hook.MESSAGE_DISPATCH_OUT.AFTER, clear_handoff)

        # Create handoff tools
        handoff_tools = [self._create_handoff_tool(sn) for sn in self._spoke_names]

        # Create hub agent
        hub_existing_instructions = self._hub_template.prototype_config.get("instructions", "")
        hub_combined_instructions = (
            f"{self._graph_instructions}\n{hub_existing_instructions}".strip()
            if self._graph_instructions else hub_existing_instructions
        )
        hub_existing_tools = list(self._hub_template.prototype_config.get("tools", []))
        
        hub_agent = self.create_node(
            self._hub_template.node_cls,
            name=self._hub_name,
            **{
                **self._hub_template.render_config(),
                "instructions": hub_combined_instructions,
                "memories": [self._shared_memory],
                "model": self._model,
                "tools": hub_existing_tools + handoff_tools,
            },
        )
        
        # Track hub output
        def record_hub_output(_node: Node, _result: dict, _input: dict) -> None:
            self._attributes_store["_last_actor"] = self._hub_name
        hub_agent.hooks.register(Node.Hook.FORWARD.AFTER, record_hub_output)
        
        # Wire hub
        self.create_edge(sender=router, receiver=hub_agent)
        self.edge_to_controller(sender=hub_agent)

        # Create spoke agents
        for i, spoke_tpl in enumerate(self._spoke_templates):
            spoke_name = self._spoke_names[i]
            
            spoke_existing_instructions = spoke_tpl.prototype_config.get("instructions", "")
            spoke_combined_instructions = (
                f"{self._graph_instructions}\n{spoke_existing_instructions}".strip()
                if self._graph_instructions else spoke_existing_instructions
            )
            
            spoke_agent = self.create_node(
                spoke_tpl.node_cls,
                name=spoke_name,
                **{
                    **spoke_tpl.render_config(),
                    "instructions": spoke_combined_instructions,
                    "memories": [self._shared_memory],
                    "model": self._model,
                },
            )
            
            # Track spoke output
            def make_spoke_hook(sname: str) -> Callable:
                def record_spoke_output(_node: Node, _result: dict, _input: dict) -> None:
                    self._attributes_store["_last_actor"] = sname
                return record_spoke_output
            spoke_agent.hooks.register(Node.Hook.FORWARD.AFTER, make_spoke_hook(spoke_name))
            
            # Wire spoke
            self.create_edge(sender=router, receiver=spoke_agent)
            self.edge_to_controller(sender=spoke_agent)

        # Wire controller -> router
        self.edge_from_controller(receiver=router)

        super().build()

    @property
    def hub_name(self) -> str:
        """Return name of the hub agent."""
        return self._hub_name

    @property
    def spoke_names(self) -> list[str]:
        """Return names of all spoke agents."""
        return self._spoke_names.copy()

