from __future__ import annotations

from masfactory.components.composed_graph.horizontal_graph import HorizontalGraph
from masfactory.components.graphs.graph import Graph
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook


class BrainstormingGraph(Graph):
    """A "brainstorming" pipeline: critics then a solver.

    This graph is implemented as a HorizontalGraph (sequential). After each
    critic runs, its output is recorded into this graph's attributes under
    `broadcast_label`.
    """

    def __init__(
        self,
        name: str,
        solver_args: dict,
        critics_args: list[dict],
        critic_keys: dict[str, str] | list[dict[str, str]],
        broadcast_label: str = "broadcast",
        pull_keys: dict[str, dict|str] | None = None,
        push_keys: dict[str, dict|str] | None = None,
        attributes: dict[str, object] | None = None,
    ):
        """Create a brainstorming pipeline.

        Args:
            name: Graph name.
            solver_args: `create_node` kwargs for the solver node.
            critics_args: `create_node` kwargs for critic nodes (executed before the solver).
            critic_keys: Edge key mapping from each critic -> next node. Can be a single dict
                applied to all critic edges, or a list aligned with `critics_args`.
            broadcast_label: Attribute key used to store per-critic outputs in this graph's attributes.
            pull_keys: Attribute pull rule for this graph.
            push_keys: Attribute push rule for this graph.
            attributes: Default attributes for this graph.
        """
        super().__init__(name, pull_keys, push_keys, attributes)
        self._solver_args = solver_args
        self._critics_args = critics_args
        self._critic_keys = critic_keys
        self._broadcast_label = broadcast_label

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build the internal HorizontalGraph and broadcast hooks."""
        # Ensure each critic can see the broadcast context if it wants.
        for critic_args in self._critics_args:
            pull_keys = critic_args.get("pull_keys", {})
            pull_keys[self._broadcast_label] = "No broadcast message yet."
            critic_args["pull_keys"] = pull_keys

        node_args_list = [*self._critics_args, self._solver_args]
        edge_keys_list = (
            self._critic_keys
            if isinstance(self._critic_keys, list)
            else [self._critic_keys] * len(self._critics_args)
        )

        self._horizontal_graph: HorizontalGraph = self.create_node(
            HorizontalGraph,
            name=f"{self.name}_horizontal_graph",
            node_args_list=node_args_list,
            edge_keys_list=edge_keys_list,
        )

        self.edge_from_entry(receiver=self._horizontal_graph, keys=self.input_keys)
        self.edge_to_exit(sender=self._horizontal_graph, keys=self.output_keys)

        self.attributes[self._broadcast_label] = {}

        def broadcast_hook(node: Node, result: dict, _input: dict) -> None:
            self.attributes[self._broadcast_label][node.name] = result

        # Build first so HorizontalGraph has created its internal node list.
        super().build()

        # Register on AFTER so we capture the actual result.
        node_list = self._horizontal_graph.node_list()
        for i in range(len(node_list) - 1):
            node_list[i].hooks.register(Node.Hook.FORWARD.AFTER, broadcast_hook)
