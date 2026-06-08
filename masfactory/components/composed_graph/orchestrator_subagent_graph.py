from __future__ import annotations

from masfactory.components.controls.logic_switch import LogicSwitch
from masfactory.components.graphs.loop import Loop
from masfactory.core.node import Node
from masfactory.core.node_template import NodeTemplate
from masfactory.utils.hook import masf_hook


class OrchestratorSubagentGraph(Loop):
    """Orchestrator-subagent loop.

    The orchestrator decides whether to delegate to a named subagent. If it emits no route,
    the orchestrator output is treated as final and the loop terminates.
    """

    def __init__(
        self,
        name: str,
        orchestrator: NodeTemplate,
        subagents: list[NodeTemplate],
        subagent_names: list[str] | None = None,
        route_key: str = "route_to",
        max_iterations: int = 10,
        orchestrator_name: str | None = None,
        router_name: str | None = None,
        orchestrator_input_keys: dict[str, dict | str] | None = None,
        orchestrator_output_keys: dict[str, dict | str] | None = None,
        subagent_output_keys: dict[str, dict | str] | None = None,
        success_keys: dict[str, dict | str] | None = None,
        pull_keys: dict[str, dict | str] | None = None,
        push_keys: dict[str, dict | str] | None = None,
        attributes: dict[str, object] | None = None,
        initial_messages: dict[str, object] | None = None,
    ):
        """Create an orchestrator-subagent graph.

        Args:
            name: Loop graph name.
            orchestrator: Template for the central routing/synthesis node.
            subagents: Templates for delegated specialist nodes.
            subagent_names: Optional names for subagent nodes.
            route_key: Field used by the orchestrator to select a subagent.
            max_iterations: Maximum orchestration turns.
            orchestrator_name: Optional internal orchestrator node name.
            router_name: Optional internal router node name.
            orchestrator_input_keys: Controller -> orchestrator edge keys.
            orchestrator_output_keys: Orchestrator -> router/subagent edge keys.
            subagent_output_keys: Subagent -> controller edge keys.
            success_keys: Router -> terminate node edge keys.
            pull_keys: Attribute pull rule for this loop.
            push_keys: Attribute push rule for this loop.
            attributes: Default attributes for this loop.
            initial_messages: Optional initial controller message cache.
        """
        if not subagents:
            raise ValueError("subagents must not be empty")
        if subagent_names is not None and len(subagent_names) != len(subagents):
            raise ValueError("subagent_names must have the same length as subagents")

        super().__init__(
            name=name,
            max_iterations=max_iterations,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
            initial_messages=initial_messages,
        )
        self._orchestrator_template = orchestrator
        self._subagent_templates = subagents
        self._subagent_names = subagent_names or [
            tpl.prototype_config.get("role_name", f"subagent_{i}")
            for i, tpl in enumerate(subagents)
        ]
        self._subagent_name_set = set(self._subagent_names)
        self._route_key = route_key
        self._orchestrator_name = orchestrator_name or f"{self.name}_orchestrator"
        self._router_name = router_name or f"{self.name}_router"
        self._orchestrator_input_keys = orchestrator_input_keys
        self._orchestrator_output_keys = orchestrator_output_keys
        self._subagent_output_keys = subagent_output_keys
        self._success_keys = success_keys
        self._orchestrator: Node | None = None
        self._router: LogicSwitch | None = None
        self._subagents: list[Node] = []

    @property
    def orchestrator(self) -> Node:
        if self._orchestrator is None:
            raise RuntimeError("OrchestratorSubagentGraph has not been built yet")
        return self._orchestrator

    @property
    def router(self) -> LogicSwitch:
        if self._router is None:
            raise RuntimeError("OrchestratorSubagentGraph has not been built yet")
        return self._router

    @property
    def subagents(self) -> list[Node]:
        return self._subagents.copy()

    def _route_target(self, message: dict[str, object]) -> str | None:
        payload = message.get("message", message)
        if isinstance(payload, dict):
            target = payload.get(self._route_key)
            if isinstance(target, str):
                return target
        target = message.get(self._route_key)
        if isinstance(target, str):
            return target
        return None

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build the orchestrator, route switch, and subagent feedback topology."""
        if self._is_built:
            return

        self._orchestrator = self.create_node(
            self._orchestrator_template,
            name=self._orchestrator_name,
        )
        self._router = self.create_node(
            LogicSwitch,
            name=self._router_name,
        )

        self.edge_from_controller(
            receiver=self._orchestrator,
            keys=self._orchestrator_input_keys,
        )
        self.create_edge(
            sender=self._orchestrator,
            receiver=self._router,
            keys=self._orchestrator_output_keys,
        )

        for i, subagent_template in enumerate(self._subagent_templates):
            subagent_name = self._subagent_names[i]
            subagent = self.create_node(subagent_template, name=subagent_name)
            self._subagents.append(subagent)
            edge_to_subagent = self.create_edge(
                sender=self._router,
                receiver=subagent,
                keys=self._orchestrator_output_keys,
            )
            self.edge_to_controller(
                sender=subagent,
                keys=self._subagent_output_keys,
            )

            def make_route(target: str):
                def route(message: dict[str, object], _attributes: dict[str, object]) -> bool:
                    return self._route_target(message) == target

                return route

            self._router.condition_binding(make_route(subagent_name), edge_to_subagent)

        edge_to_terminate = self.edge_to_terminate_node(
            sender=self._router,
            keys=self._success_keys,
        )

        def route_to_terminate(message: dict[str, object], _attributes: dict[str, object]) -> bool:
            target = self._route_target(message)
            return target is None or target not in self._subagent_name_set

        self._router.condition_binding(route_to_terminate, edge_to_terminate)

        super().build()
