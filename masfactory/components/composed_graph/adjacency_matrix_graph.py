from __future__ import annotations

import numpy as np

from masfactory.components.graphs.graph import Graph
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook


class AdjacencyMatrixGraph(Graph):
    """Graph defined by an adjacency matrix.

    Node index convention:
    - 0: internal entry (placeholder args ignored)
    - 1..n-2: user nodes
    - n-1: internal exit (placeholder args ignored)

    Adjacency matrix cell semantics:
    - None: edge exists with default keys
    - dict: edge exists with provided keys (may be empty)
    - otherwise (0/False/etc): no edge
    """

    def __init__(
        self,
        name: str,
        node_args_list: list[dict],
        adjacency_matrix: np.ndarray,
        pull_keys: dict[str, dict|str] | None = None,
        push_keys: dict[str, dict|str] | None = None,
        attributes: dict[str, object] | None = None,
    ):
        """Create a graph from node configs and an adjacency matrix.

        Args:
            name: Graph name.
            node_args_list: `create_node(**kwargs)` kwargs per node index. Index 0 and n-1 are
                reserved for internal ENTRY/EXIT placeholders and their args are ignored.
            adjacency_matrix: A square `n x n` matrix. Cells follow the class-level semantics:
                `None`/`dict` means an edge exists, other values mean no edge.
            pull_keys: Attribute pull rule for this graph.
            push_keys: Attribute push rule for this graph.
            attributes: Default attributes for this graph.
        """
        super().__init__(name, pull_keys, push_keys, attributes)
        self._node_args_list = node_args_list
        self._adjacency_matrix = adjacency_matrix

        n_nodes = len(node_args_list)
        if n_nodes <= 2:
            raise ValueError(
            f"Node count {n_nodes} must be greater than 2, because node 0 is the entry "
            "and node n-1 is the exit; their args are ignored."
            )
        if adjacency_matrix.shape != (n_nodes, n_nodes):
            raise ValueError(
                f"Adjacency matrix shape {adjacency_matrix.shape} does not match node count {n_nodes}"
            )

    @staticmethod
    def _edge_keys_or_default(keys: dict | None) -> dict:
        return {"message": "The message from the last node."} if keys is None else keys

    @staticmethod
    def _has_edge(value) -> bool:
        return value is None or isinstance(value, dict)

    @staticmethod
    def _get_edge_keys(value) -> dict | None:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        return None

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Create nodes and edges based on the adjacency matrix."""
        n_nodes = len(self._node_args_list)

        # Only create user nodes (1..n-2). 0 and n-1 are placeholders.
        node_list: list[Node | None] = [None] * n_nodes
        for i in range(1, n_nodes - 1):
            node_list[i] = self.create_node(**self._node_args_list[i])

        for i in range(n_nodes):
            for j in range(n_nodes):
                value = self._adjacency_matrix[i, j]
                if not self._has_edge(value):
                    continue

                if i == 0 and j == n_nodes - 1:
                    raise ValueError("Entry node cannot connect directly to exit node")
                if j == 0:
                    raise ValueError("Entry node cannot have incoming edges")
                if i == n_nodes - 1:
                    raise ValueError("Exit node cannot have outgoing edges")

                edge_keys = self._edge_keys_or_default(self._get_edge_keys(value))

                if i == 0:
                    self.edge_from_entry(receiver=node_list[j], keys=edge_keys)
                elif j == n_nodes - 1:
                    self.edge_to_exit(sender=node_list[i], keys=edge_keys)
                else:
                    self.create_edge(sender=node_list[i], receiver=node_list[j], keys=edge_keys)

        super().build()
