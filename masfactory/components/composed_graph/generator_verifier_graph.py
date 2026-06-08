from __future__ import annotations

import inspect
from typing import Callable

from masfactory.components.controls.logic_switch import LogicSwitch
from masfactory.components.graphs.loop import Loop
from masfactory.core.node import Node
from masfactory.core.node_template import NodeTemplate
from masfactory.utils.hook import masf_hook


class GeneratorVerifierGraph(Loop):
    """Generator-verifier retry loop.

    The generator produces a candidate result, the verifier evaluates it, and a switch routes
    accepted verifier output to termination or rejected output back to the loop controller.
    """

    def __init__(
        self,
        name: str,
        generator: NodeTemplate,
        verifier: NodeTemplate,
        max_iterations: int = 3,
        accept_condition_function: Callable | None = None,
        generator_name: str | None = None,
        verifier_name: str | None = None,
        decision_name: str | None = None,
        generator_input_keys: dict[str, dict | str] | None = None,
        generator_output_keys: dict[str, dict | str] | None = None,
        verifier_output_keys: dict[str, dict | str] | None = None,
        retry_keys: dict[str, dict | str] | None = None,
        success_keys: dict[str, dict | str] | None = None,
        pull_keys: dict[str, dict | str] | None = None,
        push_keys: dict[str, dict | str] | None = None,
        attributes: dict[str, object] | None = None,
        initial_messages: dict[str, object] | None = None,
    ):
        """Create a generator-verifier coordination graph.

        Args:
            name: Loop graph name.
            generator: Template for the node that creates candidates.
            verifier: Template for the node that checks candidates.
            max_iterations: Maximum generator-verifier attempts.
            accept_condition_function: Optional predicate deciding verifier acceptance. Supported
                signatures are `(message)` and `(message, attributes)`.
            generator_name: Optional internal generator node name.
            verifier_name: Optional internal verifier node name.
            decision_name: Optional internal decision switch name.
            generator_input_keys: Controller -> generator edge keys.
            generator_output_keys: Generator -> verifier edge keys.
            verifier_output_keys: Verifier -> decision switch edge keys.
            retry_keys: Decision switch -> controller edge keys for rejected output.
            success_keys: Decision switch -> terminate node edge keys for accepted output.
            pull_keys: Attribute pull rule for this loop.
            push_keys: Attribute push rule for this loop.
            attributes: Default attributes for this loop.
            initial_messages: Optional initial controller message cache.
        """
        super().__init__(
            name=name,
            max_iterations=max_iterations,
            terminate_condition_function=None,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
            initial_messages=initial_messages,
        )
        self._generator_template = generator
        self._verifier_template = verifier
        self._accept_condition_function = (
            accept_condition_function or self._default_accept_condition
        )
        self._generator_name = generator_name or f"{self.name}_generator"
        self._verifier_name = verifier_name or f"{self.name}_verifier"
        self._decision_name = decision_name or f"{self.name}_decision"
        self._generator_input_keys = generator_input_keys
        self._generator_output_keys = generator_output_keys
        self._verifier_output_keys = verifier_output_keys
        self._retry_keys = retry_keys
        self._success_keys = success_keys
        self._generator: Node | None = None
        self._verifier: Node | None = None
        self._decision: LogicSwitch | None = None

    @property
    def generator(self) -> Node:
        if self._generator is None:
            raise RuntimeError("GeneratorVerifierGraph has not been built yet")
        return self._generator

    @property
    def verifier(self) -> Node:
        if self._verifier is None:
            raise RuntimeError("GeneratorVerifierGraph has not been built yet")
        return self._verifier

    @property
    def decision(self) -> LogicSwitch:
        if self._decision is None:
            raise RuntimeError("GeneratorVerifierGraph has not been built yet")
        return self._decision

    def _default_accept_condition(
        self,
        message: dict[str, object],
        _attributes: dict[str, object] | None = None,
    ) -> bool:
        payload = message.get("message", message)
        if isinstance(payload, dict):
            for key in ("accepted", "verified", "success"):
                value = payload.get(key)
                if isinstance(value, bool):
                    return value
        for key in ("accepted", "verified", "success"):
            value = message.get(key)
            if isinstance(value, bool):
                return value
        return False

    def _is_accepted(
        self,
        message: dict[str, object],
        attributes: dict[str, object],
    ) -> bool:
        cache_key = "_generator_verifier_accept_cache"
        cached = attributes.get(cache_key)
        if (
            isinstance(cached, tuple)
            and len(cached) == 2
            and cached[0] == id(message)
        ):
            return bool(cached[1])

        param_count = len(inspect.signature(self._accept_condition_function).parameters)
        if param_count == 1:
            accepted = bool(self._accept_condition_function(message))
        elif param_count == 2:
            accepted = bool(self._accept_condition_function(message, attributes))
        else:
            raise ValueError(
                "accept_condition_function must have 1 or 2 parameters: "
                "(message) or (message, attributes)"
            )
        attributes[cache_key] = (id(message), accepted)
        return accepted

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build generator, verifier, and decision switch topology."""
        if self._is_built:
            return

        self._generator = self.create_node(
            self._generator_template,
            name=self._generator_name,
        )
        self._verifier = self.create_node(
            self._verifier_template,
            name=self._verifier_name,
        )
        self._decision = self.create_node(
            LogicSwitch,
            name=self._decision_name,
        )

        self.edge_from_controller(
            receiver=self._generator,
            keys=self._generator_input_keys,
        )
        self.create_edge(
            sender=self._generator,
            receiver=self._verifier,
            keys=self._generator_output_keys,
        )
        self.create_edge(
            sender=self._verifier,
            receiver=self._decision,
            keys=self._verifier_output_keys,
        )

        edge_to_controller = self.edge_to_controller(
            sender=self._decision,
            keys=self._retry_keys,
        )
        edge_to_terminate = self.edge_to_terminate_node(
            sender=self._decision,
            keys=self._success_keys,
        )

        def route_to_terminate(message: dict[str, object], attributes: dict[str, object]) -> bool:
            return self._is_accepted(message, attributes)

        def route_to_controller(message: dict[str, object], attributes: dict[str, object]) -> bool:
            return not self._is_accepted(message, attributes)

        self._decision.condition_binding(route_to_controller, edge_to_controller)
        self._decision.condition_binding(route_to_terminate, edge_to_terminate)

        super().build()
