"""
MeshGraph - Multi-agent mesh composite component using standard masfactory patterns.

This is a composite component (class-based) that creates a multi-agent mesh
with round-robin discussion using standard Loop + LogicSwitch + Agent.
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


class MeshGraph(Loop):
    """Multi-agent mesh composite component with round-robin discussion.

    A composite component that creates a Loop with multiple agents taking turns
    responding in round-robin order. Uses standard masfactory components internally.
    """

    def __init__(
        self,
        name: str,
        agents: list[NodeTemplate],
        model: Model,
        graph_instructions: str = "",
        max_iterations: int = 10,
        shared_memory: HistoryMemory | None = None,
        terminate_condition_function: Callable | None = None,
        pull_keys: dict | None = None,
        push_keys: dict | None = None,
        attributes: dict | None = None,
    ):
        """Create a MeshGraph composite component.

        Args:
            name: Name of this mesh graph.
            agents: List of Agent NodeTemplates to include in the mesh.
            model: Model adapter for agents.
            graph_instructions: Shared instructions prepended to all agents.
            max_iterations: Maximum number of loop iterations.
            shared_memory: Optional shared HistoryMemory. Auto-created if None.
            terminate_condition_function: Custom termination predicate.
            pull_keys: Attribute pull rule for this loop.
            push_keys: Attribute push rule for this loop.
            attributes: Initial loop attributes.
        """
        self._agent_templates = agents
        self._model = model
        self._graph_instructions = graph_instructions
        
        # Create shared memory if not provided
        self._shared_memory = shared_memory or HistoryMemory(top_k=100, memory_size=100)
        
        # Extract agent names
        self._agent_names = [
            tpl.prototype_config.get("role_name", f"agent_{i}")
            for i, tpl in enumerate(agents)
        ]
        
        # Default termination: check for "FINAL ANSWER"
        if terminate_condition_function is None:
            terminate_condition_function = self._default_terminate_condition
        
        super().__init__(
            name=name,
            max_iterations=max_iterations,
            terminate_condition_function=terminate_condition_function,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
        )

    def _default_terminate_condition(self, message: dict, attributes: dict) -> bool:
        """Default termination: check for 'FINAL ANSWER' in output."""
        for key in ("output", "message", "input"):
            content = message.get(key, "")
            if isinstance(content, str) and "FINAL ANSWER" in content.upper():
                return True
        return False

    def _create_round_robin_condition(self, agent_index: int) -> Callable:
        """Create a round-robin routing condition for an agent."""
        total = len(self._agent_names)
        
        def condition(message: dict, attributes: dict) -> bool:
            iteration = attributes.get("current_iteration", 0)
            return (iteration - 1) % total == agent_index
        
        return condition

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build the mesh topology: controller -> router -> agents -> controller."""
        if self._is_built:
            return

        # Build routing conditions
        routes: dict[str, Callable] = {}
        for i, agent_name in enumerate(self._agent_names):
            routes[agent_name] = self._create_round_robin_condition(i)

        # Create router
        router = self.create_node(
            LogicSwitch,
            name=f"{self.name}_router",
            routes=routes,
        )

        # Create agent nodes
        for i, agent_tpl in enumerate(self._agent_templates):
            agent_name = self._agent_names[i]
            
            # Combine instructions
            existing_instructions = agent_tpl.prototype_config.get("instructions", "")
            combined_instructions = (
                f"{self._graph_instructions}\n{existing_instructions}".strip()
                if self._graph_instructions else existing_instructions
            )
            
            # Create agent with enhanced config
            agent = self.create_node(
                agent_tpl.node_cls,
                name=agent_name,
                **{
                    **agent_tpl.render_config(),
                    "instructions": combined_instructions,
                    "memories": [self._shared_memory],
                    "model": self._model,
                },
            )
            
            # Wire: router -> agent
            self.create_edge(sender=router, receiver=agent)
            
            # Wire: agent -> controller
            self.edge_to_controller(sender=agent)

        # Wire: controller -> router
        self.edge_from_controller(receiver=router)

        super().build()

    @property
    def agent_names(self) -> list[str]:
        """Return names of all agents in the mesh."""
        return self._agent_names.copy()

