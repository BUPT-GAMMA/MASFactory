from __future__ import annotations

from masfactory.components.custom_node import CustomNode
from masfactory.components.graphs.graph import Graph
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook


class MessageBusGraph(Graph):
    """Publisher-bus-subscriber graph with shared bus history.

    Entry input is fanned out to publisher nodes. Publisher outputs are merged by a central bus
    node, recorded in this graph's attributes, then fanned out to subscriber nodes.
    """

    def __init__(
        self,
        name: str,
        publisher_configs: list[dict],
        subscriber_configs: list[dict],
        bus_state_key: str = "bus_messages",
        bus_name: str | None = None,
        pull_keys: dict[str, dict | str] | None = None,
        push_keys: dict[str, dict | str] | None = None,
        attributes: dict[str, object] | None = None,
    ):
        """Create a message bus graph.

        Args:
            name: Graph name.
            publisher_configs: Publisher definitions. Each item accepts:
                - `node`: kwargs for `create_node` (must include `cls` and `name`)
                - `input_keys`: optional entry -> publisher edge keys
                - `publish_keys`: optional publisher -> bus edge keys
            subscriber_configs: Subscriber definitions. Each item accepts:
                - `node`: kwargs for `create_node` (must include `cls` and `name`)
                - `subscription_keys`: optional bus -> subscriber edge keys
                - `output_keys`: optional subscriber -> exit edge keys
            bus_state_key: Attribute and message key used for bus history.
            bus_name: Optional internal bus node name.
            pull_keys: Attribute pull rule for this graph.
            push_keys: Attribute push rule for this graph.
            attributes: Default attributes for this graph.
        """
        init_attrs = {} if attributes is None else dict(attributes)
        init_attrs.setdefault(bus_state_key, [])
        super().__init__(name, pull_keys, push_keys, init_attrs)
        if not publisher_configs:
            raise ValueError("publisher_configs must not be empty")
        if not subscriber_configs:
            raise ValueError("subscriber_configs must not be empty")
        self._publisher_configs = publisher_configs
        self._subscriber_configs = subscriber_configs
        self._bus_state_key = bus_state_key
        self._bus_name = bus_name or f"{self.name}_bus"
        self._publishers: list[Node] = []
        self._subscribers: list[Node] = []
        self._bus: CustomNode | None = None

    @property
    def publishers(self) -> list[Node]:
        return self._publishers.copy()

    @property
    def subscribers(self) -> list[Node]:
        return self._subscribers.copy()

    @property
    def bus(self) -> CustomNode:
        if self._bus is None:
            raise RuntimeError("MessageBusGraph has not been built yet")
        return self._bus

    def _bus_forward(
        self,
        input_msg: dict[str, object],
        attributes: dict[str, object],
    ) -> dict[str, object]:
        history = list(attributes.get(self._bus_state_key, []))
        payload = input_msg.copy()
        history.append(payload)
        return {**payload, self._bus_state_key: history}

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build publisher, bus, and subscriber topology."""
        if self._is_built:
            return

        self._bus = self.create_node(
            CustomNode,
            name=self._bus_name,
            forward=self._bus_forward,
            pull_keys=None,
            push_keys={self._bus_state_key: "Shared message bus history."},
        )

        for publisher_config in self._publisher_configs:
            node_args = publisher_config["node"]
            publisher = self.create_node(**node_args)
            self._publishers.append(publisher)
            self.edge_from_entry(
                receiver=publisher,
                keys=publisher_config.get("input_keys"),
            )
            self.create_edge(
                sender=publisher,
                receiver=self._bus,
                keys=publisher_config.get("publish_keys"),
            )

        for subscriber_config in self._subscriber_configs:
            node_args = subscriber_config["node"]
            subscriber = self.create_node(**node_args)
            self._subscribers.append(subscriber)
            self.create_edge(
                sender=self._bus,
                receiver=subscriber,
                keys=subscriber_config.get("subscription_keys"),
            )
            self.edge_to_exit(
                sender=subscriber,
                keys=subscriber_config.get("output_keys"),
            )

        super().build()
