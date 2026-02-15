from __future__ import annotations

from masfactory.components.graphs.graph import Graph
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook


class HorizontalGraph(Graph):
    """Sequential (linear) graph.

    Creates nodes from `node_args_list` and connects them in order:
    `ENTRY -> node[0] -> node[1] -> ... -> node[-1] -> EXIT`.

    The ENTRY edge uses this graph's `input_keys`, and the EXIT edge uses `output_keys`.
    Edges between nodes use `edge_keys_list`.
    """

    def __init__(
        self,
        name: str,
        node_args_list: list[dict],
        edge_keys_list: list[dict] | dict,
        pull_keys: dict[str, dict | str] | None = None,
        push_keys: dict[str, dict | str] | None = None,
        attributes: dict[str, object] | None = None,
    ):
        """Create a sequential graph.

        Args:
            name: Graph name.
            node_args_list: `create_node(**kwargs)` kwargs for each node, in execution order.
            edge_keys_list: Edge key mapping(s) for node[i] -> node[i+1]. If a dict is provided,
                it is reused for all internal edges. If a list is provided, it must have length
                `len(node_args_list) - 1`.
            pull_keys: Attribute pull rule for this graph.
            push_keys: Attribute push rule for this graph.
            attributes: Default attributes for this graph.
        """
        super().__init__(name, pull_keys, push_keys, attributes)

        self._node_args_list = node_args_list
        if isinstance(edge_keys_list, dict):
            self._edge_keys_list = [edge_keys_list] * max(len(node_args_list) - 1, 0)
        else:
            self._edge_keys_list = edge_keys_list

        expected_edge_count = max(len(node_args_list) - 1, 0)
        if len(self._edge_keys_list) != expected_edge_count:
            raise ValueError(
                "edge_keys_list length must be len(node_args_list) - 1 "
                f"(got {len(self._edge_keys_list)} for {len(node_args_list)} nodes)"
            )

        self._node_list: list[Node] = []

    def node_list(self) -> list[Node]:
        return self._node_list

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        for node_args in self._node_args_list:
            node: Node = self.create_node(**node_args)
            self._node_list.append(node)

        for i in range(len(self._node_list)):
            if i == 0:
                self.edge_from_entry(receiver=self._node_list[0], keys=self.input_keys)
            if i < len(self._node_list) - 1:
                self.create_edge(
                    sender=self._node_list[i],
                    receiver=self._node_list[i + 1],
                    keys=self._edge_keys_list[i],
                )
            else:
                self.edge_to_exit(sender=self._node_list[-1], keys=self.output_keys)

        super().build()

