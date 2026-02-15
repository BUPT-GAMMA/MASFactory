from typing import Callable
from masfactory.components.graphs.graph import Graph
from masfactory.components.agents.agent import Agent
from masfactory.core.node import Node
from masfactory.components.composed_graph.vertical_decision_graph import VerticalDecisionGraph
from masfactory.components.custom_node import CustomNode
from masfactory.utils.hook import masf_hook

class VerticalSolverFirstDecisionGraph(Graph):
    """A decision graph that runs a solver once before entering a VerticalDecisionGraph.

    This pattern is useful when you want to produce an initial draft/plan, then run a critic/solver
    refinement loop around that draft.
    """
    
    def __init__(
        self,
        name: str,
        prepend_solver_args: dict,
        prepend_solver_output_keys: dict[str, str],
        critics_args: list[dict],
        critics_output_keys_list: list[dict[str, str]],
        solver_args: dict,
        solver_input_keys: dict[str, str],
        aggregator_args: dict,
        max_inner_turns: int = 3,
        controller_to_solver_keys: dict[str, str] | None = None,
        terminate_condition_function: Callable | None = None,
        terminate_condition_prompt: str | None = None,
        pull_keys: dict[str, dict|str] | None = None,
        push_keys: dict[str, dict|str] | None = None,
        initial_messages: dict[str, object] | None = None,
        attributes: dict[str, object] | None = None,
        pre_solver_terminate_condition_function: Callable | None = None,
        entry_to_vertical_decision_graph_keys: dict[str, str] | None = None,
    ):
        """Create a VerticalSolverFirstDecisionGraph.

        Args:
            name: Graph name.
            prepend_solver_args: `create_node(**kwargs)` kwargs for the prepend solver node.
            prepend_solver_output_keys: Edge key mapping from prepend solver -> VerticalDecisionGraph.
            critics_args: `create_node(**kwargs)` kwargs for critic nodes inside VerticalDecisionGraph.
            critics_output_keys_list: Per-critic edge key mapping inside VerticalDecisionGraph.
            solver_args: `create_node(**kwargs)` kwargs for the loop solver node inside VerticalDecisionGraph.
            solver_input_keys: Keys used when routing critic feedback into the loop solver.
            aggregator_args: Optional `create_node(**kwargs)` kwargs for an aggregator node.
            max_inner_turns: Maximum number of loop iterations.
            controller_to_solver_keys: Optional extra keys passed from controller -> solver each turn.
            terminate_condition_function: Optional loop termination predicate.
            terminate_condition_prompt: Optional natural language termination condition.
            pull_keys: Attribute pull rule for this graph.
            push_keys: Attribute push rule for this graph.
            initial_messages: Optional initial messages passed to the loop controller.
            attributes: Default attributes for this graph.
            pre_solver_terminate_condition_function: Optional pre-solver predicate inside VerticalDecisionGraph.
            entry_to_vertical_decision_graph_keys: Optional extra keys passed from ENTRY -> VerticalDecisionGraph.
        """
        super().__init__(name=name, pull_keys=pull_keys, push_keys=push_keys, attributes=attributes)
        
        self._prepend_solver_args = prepend_solver_args
        self._prepend_solver_output_keys = prepend_solver_output_keys
        self._critics_args = critics_args
        self._critics_output_keys_list = critics_output_keys_list
        self._solver_args = solver_args
        self._aggregator_args = aggregator_args
        self._max_inner_turns = max_inner_turns
        self._terminate_condition_function = terminate_condition_function
        self._terminate_condition_prompt = terminate_condition_prompt
        self._critics_output_keys_list = critics_output_keys_list
        self._solver_input_keys = solver_input_keys
        self._initial_messages = {} if initial_messages is None else dict(initial_messages)
        self._controller_to_solver_keys = controller_to_solver_keys
        self._pre_solver_terminate_condition_function = pre_solver_terminate_condition_function
        self._entry_to_vertical_decision_graph_keys = entry_to_vertical_decision_graph_keys
        self._prepend_solver = None
        self._vertical_decision_graph: VerticalDecisionGraph = None

    @property
    def prepend_solver(self) -> Agent:
        return self._prepend_solver

    @property
    def critics(self) -> list[Agent]:
        return self._vertical_decision_graph.critics

    @property
    def solver(self) -> Agent:
        return self._vertical_decision_graph.solver

    @property
    def vertical_decision_graph(self) -> VerticalDecisionGraph:
        return self._vertical_decision_graph

    @property
    def aggregator(self) -> CustomNode:
        return self.vertical_decision_graph.aggregator

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build the internal prepend-solver + VerticalDecisionGraph topology."""
        self._vertical_decision_graph = self.create_node(
            VerticalDecisionGraph,
            name=f"{self.name}_vertical_decision_graph",
            solver_args=self._solver_args,
            critics_args=self._critics_args,
            critics_output_keys_list=self._critics_output_keys_list,
            solver_input_keys=self._solver_input_keys,
            aggregator_args=self._aggregator_args,
            max_inner_turns=self._max_inner_turns,
            controller_to_solver_keys=self._controller_to_solver_keys,
            terminate_condition_function=self._terminate_condition_function,
            terminate_condition_prompt=self._terminate_condition_prompt,
            initial_messages=self._initial_messages,
            pre_solver_terminate_condition_function=self._pre_solver_terminate_condition_function,
        ) 

        self._prepend_solver = self.create_node(**self._prepend_solver_args)

        self.edge_from_entry( 
            receiver=self._prepend_solver,
            keys=self.input_keys 
        )
        if self._entry_to_vertical_decision_graph_keys:
            self.edge_from_entry(
                receiver=self._vertical_decision_graph,
                keys=self._entry_to_vertical_decision_graph_keys,
            )
        self.create_edge(
            sender=self._prepend_solver,
            receiver=self._vertical_decision_graph,
            keys=self._prepend_solver_output_keys
        )
        self.edge_to_exit(
            sender=self._vertical_decision_graph,
            keys=self.output_keys
        )
        super().build()
