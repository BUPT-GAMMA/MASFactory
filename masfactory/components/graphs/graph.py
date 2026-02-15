from masfactory.core.node import Node
from masfactory.core.gate import Gate
from masfactory.core.edge import Edge
from typing import Callable, Mapping, Tuple
import logging
from masfactory.components.graphs.base_graph import BaseGraph
from masfactory.core.message import MessageFormatter,JsonMessageFormatter
from masfactory.components.graphs.internal_nodes import InternalGraphNode
from masfactory.utils.hook import masf_hook
from masfactory.core.node_template import NodeTemplate

class Graph(BaseGraph):
    """
    Composite graph node with internal entry and exit ports.

    Graph is both a node and a container. It can be nested inside another graph.
    """
    def __init__(
        self, 
        name, 
        pull_keys: dict[str, dict|str] | None = None, 
        push_keys: dict[str, dict|str] | None = None, 
        attributes: dict[str, object] | None = None,
        edges: list[tuple[str, str] | tuple[str, str, dict[str, dict|str] ]]|None=None,
        nodes: list[tuple] | None = None,
        build_func:Callable|None = None,
    ):
        """Create a composite graph node with internal entry/exit ports.

        Args:
            name: Graph name.
            pull_keys: Attribute pull rule for this graph.
            push_keys: Attribute push rule for this graph.
            attributes: Default attributes for this graph.
            edges: Optional declarative edge definitions. Each item is either:
                - `(from_name, to_name)`
                - `(from_name, to_name, edge_keys)`
            nodes: Optional declarative node definitions passed into `create_node`.
            build_func: Optional custom build function executed before child build.
                Signature: `(graph: Graph) -> None`.
        """
        if attributes is None:
            attributes = {}
        super().__init__(name, pull_keys, push_keys, attributes, build_func=build_func)
        self._init_nodes = nodes
        self._init_edges = edges
        class EntryNode(InternalGraphNode):
            def __init__(self, name, gate_close_callback:Callable|None=None):
                super().__init__(name, gate_close_callback)
                self.input: dict[str,object] = {}
            @masf_hook(Node.Hook.FORWARD)
            def _forward(self,input:dict[str,object]) -> dict[str,object]:
                return input
            def _message_aggregate_in(self) -> dict[str,object]:     
                return self.input
            def _update_gate_state(self):
                pass
            @masf_hook(Node.Hook.BUILD)
            def build(self):
                self._is_built = True

        class ExitNode(InternalGraphNode):
            def __init__(self, name, gate_close_callback:Callable|None=None):
                super().__init__(name, gate_close_callback)
                self._output = {}
            @masf_hook(Node.Hook.FORWARD)
            def _forward(self,input:dict[str,object]) -> dict[str,object]:
                return input
            def _message_dispatch_out(self,message:dict[str,object]):
                self._output = message
                self._gate = Gate.OPEN
            @masf_hook(Node.Hook.BUILD)
            def build(self):
                self._is_built = True

        self._entry: EntryNode = EntryNode(self.name + "_entry",self._close)
        self._exit: ExitNode = ExitNode(self.name + "_exit",self._close)
        self._entry._set_owner(self)
        self._exit._set_owner(self)

    def _iter_internal_nodes(self) -> list[Node]:
        return [self._entry, self._exit]

    def _label_internal_node(self, node: Node) -> str | None:
        if node is self._entry:
            return "entry" if type(self).__name__ == "RootGraph" else f"{self.name}.entry"
        if node is self._exit:
            return "exit" if type(self).__name__ == "RootGraph" else f"{self.name}.exit"
        return None

    def _close(self):
        self._gate = Gate.CLOSED
        self._close_out_edges()

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build the graph by materializing declarative nodes/edges and building children.

        This method supports a declarative style where `nodes=[...]` and `edges=[...]` are
        provided at construction time. It creates the referenced nodes, wires edges (including
        `entry`/`exit` ports), then calls `BaseGraph.build()` and builds internal entry/exit
        nodes.

        The build is idempotent: calling `build()` multiple times is a no-op after the first
        successful build.
        """
        if self._is_built:
            return
        # Create nodes from declarative `nodes` entries.
        if self._init_nodes:
            for item in self._init_nodes:
                if len(item) < 2:
                    raise ValueError(f"Invalid node definition: {item}")
                name = item[0]
                target = item[1]
                others = item[2:]
                
                # Unpack kwargs if the last arg is a dict?
                # BaseGraph.create_node handles kwargs in *args if target is NodeTemplate (via check I added)
                # But for Node class instantiation, we might want to be explicit.
                # However, create_node(cls, *args, **kwargs) passes args/kwargs to constructor.
                # So just passing *others is fine.
                
                self.create_node(target, *others, name=name)

        # Create edges from declarative `edges` entries.
        if self._init_edges:
            for edge_def in self._init_edges:
                if len(edge_def) == 2:
                    src_name, dst_name = edge_def
                    keys = None
                elif len(edge_def) == 3:
                    src_name, dst_name, keys = edge_def
                else:
                    raise ValueError(f"Invalid edge definition: {edge_def}")
                src_token = str(src_name).strip()
                dst_token = str(dst_name).strip()
                src_key = src_token.lower()
                dst_key = dst_token.lower()
                if src_key == "entry":
                    src_node = self._entry
                else:
                    src_node = self._nodes.get(src_token)
                    if src_node is None:
                        raise ValueError(f"Source node '{src_name}' not found in graph '{self.name}'")

                if dst_key == "exit":
                    dst_node = self._exit
                else:
                    dst_node = self._nodes.get(dst_token)
                    if dst_node is None:
                        raise ValueError(f"Destination node '{dst_name}' not found in graph '{self.name}'")

                if src_key == "entry":
                    self.edge_from_entry(dst_node, keys)
                elif dst_key == "exit":
                    self.edge_to_exit(src_node, keys)
                else:
                    self.create_edge(src_node, dst_node, keys)
        
        super().build()
        self._entry.build()
        self._exit.build()

    def check_built(self) -> bool:
        return super().check_built() and self._entry.check_built() and self._exit.check_built()
    @masf_hook(Node.Hook.FORWARD)
    def _forward(self, input:dict[str,object]) -> dict[str,object]:
        """Run one graph invocation and return exit output."""
        self.reset_gate()
        self._entry.input = input
        # Prevent output leaking across invocations if the graph exits early.
        self._exit._output = {}
        self._entry.execute(self._attributes_store)
        max_iterations = 10000

        for iteration in range(max_iterations):
            if self._exit.is_ready or self._gate != Gate.OPEN:
                break

            executed_any = False
            for node in self._nodes.values():
                if node.is_ready and self._gate == Gate.OPEN:
                    node.execute(self._attributes_store)
                    executed_any = True
                    break

            if not executed_any:
                logging.warning(
                    "Graph %s is stuck (no ready nodes at iteration %d).",
                    self.name,
                    iteration,
                )
                break
        else:
            logging.warning(
                "Graph %s exceeded max iterations (%d).",
                self.name,
                max_iterations,
            )

        if self._exit.is_ready:
            self._exit.execute(self._attributes_store)
        return self._exit.output.copy()
    
    def edge_from_entry(self,
            receiver: Node,
            keys: dict[str,dict|str]|None=None):
        """Create an edge from internal entry to `receiver`."""
        if receiver is not self._exit:
            receiver_node = self._nodes.get(receiver.name)
            if receiver_node is None:
                raise ValueError(
                    f"Receiver node '{receiver.name}' not found in graph '{self.name}'"
                )
            if receiver_node is not receiver:
                raise ValueError(
                    f"Receiver node instance mismatch for '{receiver.name}' in graph '{self.name}'"
                )

        for existing in self._entry.out_edges:
            if existing._receiver is receiver:
                raise ValueError(
                    f"duplicate edge: {self._entry.name} -> {receiver.name} already exists in graph '{self.name}'"
                )

        edge = Edge(self._entry, receiver, keys)
        self._edges.append(edge)
        self._entry.add_out_edge(edge)
        receiver.add_in_edge(edge)
        return edge

    def edge_to_exit(self,
            sender: Node,
            keys: dict[str,dict|str]|None=None,
            ):
        """Create an edge from `sender` to internal exit."""
        if sender is not self._entry:
            sender_node = self._nodes.get(sender.name)
            if sender_node is None:
                raise ValueError(f"Sender node '{sender.name}' not found in graph '{self.name}'")
            if sender_node is not sender:
                raise ValueError(
                    f"Sender node instance mismatch for '{sender.name}' in graph '{self.name}'"
                )

        for existing in sender.out_edges:
            if existing._receiver is self._exit:
                raise ValueError(
                    f"duplicate edge: {sender.name} -> {self._exit.name} already exists in graph '{self.name}'"
                )

        edge = Edge(sender, self._exit, keys)
        self._edges.append(edge)
        sender.add_out_edge(edge)
        self._exit.add_in_edge(edge)
        return edge
    def reset(self):
        super().reset()
        self._entry.reset()
        self._exit.reset()
    def reset_gate(self):
        self._entry.reset_gate()
        self._exit.reset_gate()
        super().reset_gate()
