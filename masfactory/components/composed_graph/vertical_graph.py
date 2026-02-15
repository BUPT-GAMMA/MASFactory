from __future__ import annotations

from masfactory.components.graphs.graph import Graph
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook


class VerticalGraph(Graph):
    """Fan-out graph.

    Runs multiple nodes in parallel (fan-out). Optionally, an aggregator node can merge
    all branch outputs before the graph exits.
    """

    def __init__(
        self,
        name: str,
        node_configs: list[dict[str, dict]],
        aggregator_args: dict | None = None,
        pull_keys: dict[str, dict|str] | None = None,
        push_keys: dict[str, dict|str] | None = None,
        attributes: dict[str, object] | None = None,
    ):
        """Create a fan-out graph with optional aggregation.

        Args:
            name: Graph name.
            node_configs: A list of branch configs. Each config dict must contain:
                - `node`: kwargs for `create_node` (must include at least `cls` and `name`)
                - `input_keys`: keys for ENTRY -> node
                - `output_keys`: keys for node -> EXIT (or node -> aggregator)
            aggregator_args: Optional kwargs for creating an aggregator node. When provided,
                all branch outputs flow into the aggregator, and only the aggregator connects to EXIT.
            pull_keys: Attribute pull rule for this graph.
            push_keys: Attribute push rule for this graph.
            attributes: Default attributes for this graph.
        """
        super().__init__(name, pull_keys, push_keys, attributes)
        self._node_configs = node_configs
        self._aggregator_args = aggregator_args
        self._node_list: list[Node] = []
        self._aggregator: Node | None = None

    @property
    def aggregator(self) -> Node | None:
        return self._aggregator

    @property
    def veritical_node_list(self) -> list[Node]:
        return self._node_list

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        if self._aggregator_args is not None:
            self._aggregator = self.create_node(**self._aggregator_args)
            # Aggregator must emit the full output schema of this VerticalGraph.
            self.edge_to_exit(sender=self._aggregator, keys=self.output_keys)

        for node_config in self._node_configs:
            node = self.create_node(**node_config["node"])
            self._node_list.append(node)

            self.edge_from_entry(receiver=node, keys=node_config["input_keys"])

            if self._aggregator is not None:
                self.create_edge(
                    sender=node,
                    receiver=self._aggregator,
                    keys=node_config["output_keys"],
                )
            else:
                self.edge_to_exit(sender=node, keys=node_config["output_keys"])

        super().build()
