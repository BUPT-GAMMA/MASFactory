from __future__ import annotations

from masfactory.components.graphs.graph import Graph
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook


class SharedStateGraph(Graph):
    """Sequential graph with a graph-level shared state attribute.

    Each internal node pulls the shared state before execution and may update it by emitting the
    configured state key in its output.
    """

    def __init__(
        self,
        name: str,
        node_configs: list[dict],
        initial_state: dict[str, object] | None = None,
        state_key: str = "shared_state",
        edge_keys_list: list[dict[str, dict | str]] | dict[str, dict | str] | None = None,
        output_keys: dict[str, dict | str] | None = None,
        pull_keys: dict[str, dict | str] | None = None,
        push_keys: dict[str, dict | str] | None = None,
        attributes: dict[str, object] | None = None,
    ):
        """Create a shared-state sequential graph.

        Args:
            name: Graph name.
            node_configs: Sequential node definitions. Each item accepts:
                - `node`: kwargs for `create_node` (must include `cls` and `name`)
                - `input_keys`: optional edge keys into this node
                - `output_keys`: optional edge keys from this node
            initial_state: Initial value stored under `state_key`.
            state_key: Attribute key used for shared state.
            edge_keys_list: Optional shared/list edge keys between adjacent nodes.
            output_keys: Optional last node -> exit edge keys.
            pull_keys: Attribute pull rule for this graph.
            push_keys: Attribute push rule for this graph.
            attributes: Default attributes for this graph.
        """
        if not node_configs:
            raise ValueError("node_configs must not be empty")
        init_attrs = {} if attributes is None else dict(attributes)
        init_attrs.setdefault(state_key, {} if initial_state is None else dict(initial_state))
        super().__init__(name, pull_keys, push_keys, init_attrs)
        self._node_configs = node_configs
        self._state_key = state_key
        self._output_keys = output_keys
        self._state_nodes: list[Node] = []

        expected_edge_count = max(len(node_configs) - 1, 0)
        if edge_keys_list is None:
            self._edge_keys_list = None
        elif isinstance(edge_keys_list, dict):
            self._edge_keys_list = [edge_keys_list] * expected_edge_count
        else:
            self._edge_keys_list = edge_keys_list
        if self._edge_keys_list is not None and len(self._edge_keys_list) != expected_edge_count:
            raise ValueError(
                "edge_keys_list length must be len(node_configs) - 1 "
                f"(got {len(self._edge_keys_list)} for {len(node_configs)} nodes)"
            )

    @property
    def state_nodes(self) -> list[Node]:
        return self._state_nodes.copy()

    def _state_pull_keys(self, node_args: dict) -> dict[str, dict | str]:
        pull_keys = dict(node_args.get("pull_keys") or {})
        pull_keys.setdefault(self._state_key, "Shared graph state.")
        return pull_keys

    def _state_push_keys(self, node_args: dict) -> dict[str, dict | str]:
        push_keys = dict(node_args.get("push_keys") or {})
        push_keys.setdefault(self._state_key, "Shared graph state.")
        return push_keys

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build the sequential state-sharing topology."""
        if self._is_built:
            return

        for node_config in self._node_configs:
            node_args = dict(node_config["node"])
            node_args["pull_keys"] = self._state_pull_keys(node_args)
            node_args["push_keys"] = self._state_push_keys(node_args)
            node = self.create_node(**node_args)
            self._state_nodes.append(node)

        for i, node in enumerate(self._state_nodes):
            if i == 0:
                self.edge_from_entry(
                    receiver=node,
                    keys=self._node_configs[i].get("input_keys"),
                )
            else:
                edge_keys = None
                if self._edge_keys_list is not None:
                    edge_keys = self._edge_keys_list[i - 1]
                edge_keys = self._node_configs[i - 1].get("output_keys", edge_keys)
                self.create_edge(
                    sender=self._state_nodes[i - 1],
                    receiver=node,
                    keys=edge_keys,
                )

            if i == len(self._state_nodes) - 1:
                self.edge_to_exit(
                    sender=node,
                    keys=self._output_keys
                    or self._node_configs[i].get("output_keys"),
                )

        super().build()
