from __future__ import annotations

from masfactory.components.custom_node import CustomNode
from masfactory.components.graphs.graph import Graph
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook


class AgentTeamGraph(Graph):
    """Fan-out team graph that collects named member outputs.

    Each team member receives the graph input. Member outputs are wrapped by member name,
    merged into `team_outputs`, and optionally passed to an aggregator node.
    """

    def __init__(
        self,
        name: str,
        member_configs: list[dict],
        aggregator_args: dict | None = None,
        team_outputs_key: str = "team_outputs",
        collector_name: str | None = None,
        aggregator_input_keys: dict[str, dict | str] | None = None,
        aggregator_output_keys: dict[str, dict | str] | None = None,
        pull_keys: dict[str, dict | str] | None = None,
        push_keys: dict[str, dict | str] | None = None,
        attributes: dict[str, object] | None = None,
    ):
        """Create an agent-team graph.

        Args:
            name: Graph name.
            member_configs: Team member definitions. Each item accepts:
                - `node`: kwargs for `create_node` (must include `cls` and `name`)
                - `input_keys`: optional entry -> member edge keys
                - `output_keys`: optional member -> wrapper edge keys
            aggregator_args: Optional kwargs for creating a final aggregator node.
            team_outputs_key: Message and attribute key for collected member outputs.
            collector_name: Optional internal collector node name.
            aggregator_input_keys: Optional collector -> aggregator edge keys.
            aggregator_output_keys: Optional aggregator/collector -> exit edge keys.
            pull_keys: Attribute pull rule for this graph.
            push_keys: Attribute push rule for this graph.
            attributes: Default attributes for this graph.
        """
        if not member_configs:
            raise ValueError("member_configs must not be empty")
        init_attrs = {} if attributes is None else dict(attributes)
        init_attrs.setdefault(team_outputs_key, {})
        super().__init__(name, pull_keys, push_keys, init_attrs)
        self._member_configs = member_configs
        self._aggregator_args = aggregator_args
        self._team_outputs_key = team_outputs_key
        self._collector_name = collector_name or f"{self.name}_collector"
        self._aggregator_input_keys = aggregator_input_keys
        self._aggregator_output_keys = aggregator_output_keys
        self._members: list[Node] = []
        self._wrappers: list[CustomNode] = []
        self._collector: CustomNode | None = None
        self._aggregator: Node | None = None

    @property
    def members(self) -> list[Node]:
        return self._members.copy()

    @property
    def collector(self) -> CustomNode:
        if self._collector is None:
            raise RuntimeError("AgentTeamGraph has not been built yet")
        return self._collector

    @property
    def aggregator(self) -> Node | None:
        return self._aggregator

    def _collector_forward(
        self,
        input_msg: dict[str, object],
        _attributes: dict[str, object],
    ) -> dict[str, object]:
        outputs = input_msg.get(self._team_outputs_key, {})
        if not isinstance(outputs, dict):
            outputs = {}
        return {self._team_outputs_key: outputs.copy()}

    def _make_wrapper_forward(self, member_name: str):
        def wrap(input_msg: dict[str, object]) -> dict[str, object]:
            return {self._team_outputs_key: {member_name: input_msg.copy()}}

        return wrap

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build team members, wrappers, collector, and optional aggregator."""
        if self._is_built:
            return

        self._collector = self.create_node(
            CustomNode,
            name=self._collector_name,
            forward=self._collector_forward,
            pull_keys=None,
            push_keys={self._team_outputs_key: "Collected team member outputs."},
        )

        for member_config in self._member_configs:
            node_args = member_config["node"]
            member = self.create_node(**node_args)
            self._members.append(member)
            wrapper = self.create_node(
                CustomNode,
                name=f"{member.name}_team_output",
                forward=self._make_wrapper_forward(member.name),
            )
            self._wrappers.append(wrapper)

            self.edge_from_entry(
                receiver=member,
                keys=member_config.get("input_keys"),
            )
            self.create_edge(
                sender=member,
                receiver=wrapper,
                keys=member_config.get("output_keys"),
            )
            self.create_edge(
                sender=wrapper,
                receiver=self._collector,
                keys={self._team_outputs_key: "Named team member output."},
            )

        if self._aggregator_args is not None:
            self._aggregator = self.create_node(**self._aggregator_args)
            self.create_edge(
                sender=self._collector,
                receiver=self._aggregator,
                keys=self._aggregator_input_keys
                or {self._team_outputs_key: "Collected team member outputs."},
            )
            self.edge_to_exit(
                sender=self._aggregator,
                keys=self._aggregator_output_keys,
            )
        else:
            self.edge_to_exit(
                sender=self._collector,
                keys=self._aggregator_output_keys
                or {self._team_outputs_key: "Collected team member outputs."},
            )

        super().build()
