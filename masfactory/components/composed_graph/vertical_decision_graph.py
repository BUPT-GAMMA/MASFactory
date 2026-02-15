from typing import Any, Callable
import inspect
from masfactory.components.agents.agent import Agent
from masfactory.components.graphs.loop import Loop
from masfactory.components.controls.logic_switch import LogicSwitch
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook

class VerticalDecisionGraph(Loop):
    """A critic/solver loop graph.

    On each iteration:
    - The controller fans out to multiple critic nodes.
    - Critic outputs are optionally aggregated and routed into the solver.
    - The solver output is routed back to the controller.

    Optionally, a pre-solver termination function can short-circuit an iteration and route to the
    terminate node without invoking the solver.
    """
    
    def __init__(
        self,
        name: str,
        solver_args: dict,
        critics_args: list[dict],
        critics_output_keys_list: list[dict[str, str]],
        solver_input_keys: dict[str, str],
        aggregator_args: dict,
        max_inner_turns: int = 3,
        controller_to_solver_keys: dict[str, str] | None = None,
        terminate_condition_function: Callable | None = None,
        terminate_condition_prompt: str | None = None,
        pull_keys: dict[str, dict|str] | None = None,
        push_keys: dict[str, dict|str] | None = None,
        attributes: dict[str, object] | None = None,
        initial_messages: dict[str, object] | None = None,
        pre_solver_terminate_condition_function: Callable | None = None,
    ):
        """Create a VerticalDecisionGraph.

        Args:
            name: Graph name.
            solver_args: `create_node(**kwargs)` kwargs for the solver node.
            critics_args: `create_node(**kwargs)` kwargs for critic nodes.
            critics_output_keys_list: Edge key mappings for critic -> solver/aggregator. When
                provided, must have the same length as `critics_args`. If `None`, critics connect
                with an empty key mapping.
            solver_input_keys: Keys used when routing aggregated critic feedback into the solver.
            aggregator_args: Optional `create_node(**kwargs)` kwargs for an aggregator node. When
                provided, critics route into the aggregator instead of directly into the solver.
            max_inner_turns: Maximum number of loop iterations.
            controller_to_solver_keys: Optional extra keys passed from controller -> solver each turn.
            terminate_condition_function: Optional loop termination predicate.
            terminate_condition_prompt: Optional natural language termination condition.
            pull_keys: Attribute pull rule for this graph.
            push_keys: Attribute push rule for this graph.
            attributes: Default attributes for this graph.
            initial_messages: Optional initial messages passed to the loop controller.
            pre_solver_terminate_condition_function: Optional predicate evaluated before solver runs.
                When it returns True, the loop routes to the terminate node directly.
        """
        
        super().__init__(
            name,
            max_iterations=max_inner_turns,
            terminate_condition_function=terminate_condition_function,
            terminate_condition_prompt=terminate_condition_prompt,
            pull_keys=pull_keys,
            push_keys=push_keys,
            initial_messages=initial_messages,
            attributes=attributes,
        )
        if max_inner_turns <= 0:
            raise ValueError("max_inner_turns must be greater than 0")
        if critics_output_keys_list is not None and len(critics_output_keys_list) != len(
            critics_args
        ):
            raise ValueError(
                "critics_output_keys_list must be None or have the same length as critics_args"
            )
        self._solver_args = solver_args
        self._critics_args = critics_args
        self._aggregator_args = aggregator_args
        self._critics_output_keys_list = critics_output_keys_list
        self._solver_input_keys = solver_input_keys
        self._solver = None
        self._critics = []
        self._aggregator = None
        self._controller_to_solver_keys = controller_to_solver_keys
        self._pre_solver_terminate_condition_function = pre_solver_terminate_condition_function

    @property
    def solver(self) -> Agent:
        return self._solver

    @property
    def critics(self) -> list[Agent]:
        return self._critics

    @property
    def aggregator(self) -> Node:
        return self._aggregator

    @masf_hook(Node.Hook.BUILD)
    def build(self):    
        """Build the internal critic/aggregator/solver topology for the loop."""
        self._solver = self.create_node(**self._solver_args)
        for critic_args in self._critics_args:
            critic = self.create_node(**critic_args)
            self._critics.append(critic)

        enable_pre_solver_terminate = self._pre_solver_terminate_condition_function is not None
        switch: LogicSwitch | None = None
        if enable_pre_solver_terminate:
            switch = self.create_node(LogicSwitch, name=f"{self.name}_pre_solver_switch")

        if self._aggregator_args is not None:
            self._aggregator = self.create_node(**self._aggregator_args)
            if not enable_pre_solver_terminate:
                self.create_edge(
                    sender=self._aggregator,
                    receiver=self._solver,
                    keys=self._solver_input_keys
                )
        for i, critic in enumerate(self._critics):
            self.edge_from_controller( 
                receiver=critic,
                keys=self.input_keys
            )
            output_keys = {}
            if self._critics_output_keys_list is not None:
                output_keys = self._critics_output_keys_list[i]
            if self._aggregator_args is not None:
                self.create_edge(
                    sender=critic,
                    receiver=self._aggregator,
                    keys=output_keys
                )

            else:
                if not enable_pre_solver_terminate:
                    self.create_edge(
                        sender=critic,
                        receiver=self._solver,
                        keys=output_keys
                    )
                else:
                    if switch is None:
                        raise RuntimeError(
                            "pre_solver_switch was expected to be created but is None"
                        )
                    self.create_edge(
                        sender=critic,
                        receiver=switch,
                        keys=output_keys
                    )

        if enable_pre_solver_terminate:
            if switch is None:
                raise RuntimeError("pre_solver_switch was expected to be created but is None")

            def _pre_solver_should_terminate(message: dict[str, object], attrs: dict[str, object]) -> bool:
                cache_key = "_pre_solver_terminate_cache"
                cached = attrs.get(cache_key)
                if (
                    isinstance(cached, tuple)
                    and len(cached) == 2
                    and cached[0] == id(message)
                ):
                    return bool(cached[1])

                func = self._pre_solver_terminate_condition_function
                if func is None:
                    result = False
                else:
                    param_count = len(inspect.signature(func).parameters)
                    if param_count == 1:
                        result = func(message)
                    elif param_count == 2:
                        result = func(message, attrs)
                    else:
                        raise ValueError(
                            "pre_solver_terminate_condition_function must have 1 or 2 parameters: (message) or (message, attributes)"
                        )

                attrs[cache_key] = (id(message), bool(result))
                return bool(result)

            def _route_to_solver(message: dict[str, object], attrs: dict[str, object]) -> bool:
                return not _pre_solver_should_terminate(message, attrs)

            def _route_to_terminate(message: dict[str, object], attrs: dict[str, object]) -> bool:
                return _pre_solver_should_terminate(message, attrs)

            controller_switch_keys: dict[str, dict | str] = {}
            # Provide current draft/solution to the switch (from controller message cache),
            # so the terminate branch can return a meaningful final output.
            controller_switch_keys.update(self.output_keys or {})
            if self._controller_to_solver_keys:
                controller_switch_keys.update(self._controller_to_solver_keys)
            if not controller_switch_keys:
                controller_switch_keys = {"message": "controller state"}
            self.edge_from_controller(receiver=switch, keys=controller_switch_keys)

            if self._aggregator is not None:
                self.create_edge(
                    sender=self._aggregator,
                    receiver=switch,
                    keys=self._solver_input_keys,
                )

                switch_to_solver_keys: dict[str, dict | str] = {}
                switch_to_solver_keys.update(self._solver_input_keys or {})
                if self._controller_to_solver_keys:
                    switch_to_solver_keys.update(self._controller_to_solver_keys)
                if not switch_to_solver_keys:
                    switch_to_solver_keys = {"message": "aggregated feedback"}

                edge_switch_to_solver = self.create_edge(
                    sender=switch,
                    receiver=self._solver,
                    keys=switch_to_solver_keys,
                )
            else:
                merged_critic_keys: dict[str, dict | str] = {}
                if self._critics_output_keys_list is not None:
                    for critic_keys in self._critics_output_keys_list:
                        merged_critic_keys.update(critic_keys or {})
                if not merged_critic_keys:
                    merged_critic_keys = {"message": "critic feedback"}

                switch_to_solver_keys = dict(merged_critic_keys)
                if self._controller_to_solver_keys:
                    switch_to_solver_keys.update(self._controller_to_solver_keys)

                edge_switch_to_solver = self.create_edge(
                    sender=switch,
                    receiver=self._solver,
                    keys=switch_to_solver_keys,
                )

            edge_switch_to_terminate = self.edge_to_terminate_node(
                sender=switch,
                keys=self.output_keys or {"message": "final output"},
            )
            switch.condition_binding(_route_to_solver, edge_switch_to_solver)
            switch.condition_binding(_route_to_terminate, edge_switch_to_terminate)
        self.edge_to_controller(
            sender=self._solver,
            keys=self.output_keys
        )

        if self._controller_to_solver_keys and not enable_pre_solver_terminate:
            self.edge_from_controller(
                receiver=self._solver,
                keys=self._controller_to_solver_keys,
            )
        
        super().build()
