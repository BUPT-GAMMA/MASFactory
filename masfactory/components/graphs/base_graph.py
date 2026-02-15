from typing import Any, Callable, TypeVar, overload

from masfactory.components.agents.single_agent import SingleAgent
from masfactory.core.edge import Edge
from masfactory.core.node import Node
from masfactory.core.node_template import NodeTemplate
from masfactory.utils.hook import masf_hook
from masfactory.utils.naming import validate_name
from masfactory.utils.selector import Selector
T = TypeVar("T", bound=Node)

class BaseGraph(Node):
    """Base class for all graph-like nodes.

    A `BaseGraph` is both a `Node` (it can be embedded) and a container that owns child nodes
    and edges. It provides helpers for creating nodes/edges and for recursive hook registration.
    """

    def __init__(
        self,
        name,
        pull_keys: dict[str, dict|str] | None = None,
        push_keys: dict[str, dict|str] | None = None,
        attributes: dict[str, object] | None = None,
        build_func:Callable|None = None,
    ):
        """Create a graph container node.

        Args:
            name: Graph name.
            pull_keys: Keys pulled from parent attributes.
            push_keys: Keys pushed back to parent attributes.
            attributes: Initial local attributes.
            build_func: Optional callback executed before child build.
                Signature: `(graph: BaseGraph) -> None`.
        """
        if attributes is None:
            attributes = {}
        super().__init__(name, pull_keys, push_keys,attributes)
        self._nodes:dict[str,Node] = {}
        self._edges:list[Edge] = []
        self._build_func = build_func

    def set_attributes(self,attributes:dict[str,object]):
        self._attributes_store = attributes
    
    @masf_hook(Node.Hook.BUILD)
    def build(self):
        if self._build_func:
            self._build_func(self)
        for node in self._nodes.values():
            node.build()
        self._is_built = True
    def check_built(self) -> bool:
        """Return whether this graph and all child nodes are built."""
        for node in self._nodes.values():
            if not node.check_built():
                return False
        return self._is_built

    @overload
    def create_node(self, cls: type[T], *args, **kwargs) -> T: ...

    @overload
    def create_node(self, cls: NodeTemplate[T], *args, **kwargs) -> T: ...

    def create_node(self, cls:type[Node] | NodeTemplate, *args, **kwargs) -> Node:
        """
        Create a node in this graph.

        Args:
            cls: Node class or NodeTemplate.
            *args: Positional constructor arguments.
            **kwargs: Keyword constructor arguments.

        Returns:
            Node: Created node instance.
        """
        name = kwargs.pop("name", None)
        if name is None and args and isinstance(args[0], str):
            name = args[0]
            args = args[1:]

        if isinstance(name, str):
            validate_name(name, kind="node name")
            reserved = {"entry", "exit"}
            try:
                from masfactory.components.graphs.loop import Loop  # noqa: WPS433
            except Exception:
                Loop = None  # type: ignore[assignment]
            if Loop is not None and isinstance(self, Loop):  # pragma: no cover
                reserved |= {"controller", "terminate"}
            if name.strip().lower() in reserved:
                raise ValueError(
                    f"Node name '{name}' is reserved in graph '{self.name}'. "
                    f"Reserved names: {sorted(reserved)}"
                )

        if isinstance(cls, NodeTemplate):
            if args:
                raise TypeError(
                    "create_node(template, ...) does not accept positional args. "
                    "Use template(**override) in declarative nodes, or pass overrides via keyword arguments."
                )

            overrides = kwargs.copy()

            if name is None:
                 raise ValueError("Name must be provided when creating node from template")

            # Build a stable creation path for template rule matching:
            # root_graph > ... > owner_graph(self) > node_name(name)
            creation_path: list[str] = []
            current: Node | None = self
            while current is not None:
                creation_path.append(current.name)
                current = current.owner
            creation_path.reverse()
            creation_path.append(name)

            def _instantiate(node_cls: type[Node], **kw) -> Node:
                return node_cls(**kw)

            node = cls._materialize(
                name=name,
                instantiate=_instantiate,
                creation_path=tuple(creation_path),
                **overrides,
            )
            
            node_cls = node.__class__
            if node_cls.__name__ == "RootGraph" or node_cls.__module__ == "masfactory.components.graphs.root_graph":
                raise ValueError(f"Class {node_cls.__name__} must not be RootGraph")
            if issubclass(node_cls, SingleAgent):
                raise ValueError(
                    f"Class {node_cls.__name__} must not be a subclass of SingleAgent"
                )

            existing = self._nodes.get(name)
            if existing is not None:
                if existing is not node:
                    raise ValueError(
                        f"Node '{name}' already exists in graph '{self.name}'."
                    )
                return existing

            self._nodes[name] = node
            node._set_owner(self)
            return node

        if not issubclass(cls, Node):
            raise TypeError(f"Class {cls.__name__} is not a subclass of Node")
        
        if cls.__name__ == "RootGraph" or cls.__module__ == "masfactory.components.graphs.root_graph":
            raise ValueError(f"Class {cls.__name__} must not be RootGraph")
        
        if issubclass(cls, SingleAgent):
            raise ValueError(
                f"Class {cls.__name__} must not be a subclass of SingleAgent"
            )
        
        if name is None:
             raise ValueError("Name must be provided when creating node from class")

        existing = self._nodes.get(name)
        if existing is not None:
            raise ValueError(f"Node '{name}' already exists in graph '{self.name}'.")

        node = cls(name, *args, **kwargs)
        node._set_owner(self)
        self._nodes[name] = node
        return node

    def create_edges(
        self,
        edges_info: list[tuple[Node, Node, dict[str, dict|str]|None]],
    ) -> list[Edge]:
        """Create multiple edges from `(sender, receiver, keys)` tuples."""
        created_edges = []
        for sender, receiver, keys in edges_info:
            edge = self.create_edge(sender, receiver, keys)
            created_edges.append(edge)
        return created_edges
    def create_edge(self,
            sender: Node,
            receiver: Node,
            keys: dict[str, dict|str] | None = None,
        ) -> Edge:
        """Create one edge between two nodes that belong to this graph."""
        sender_node = self._nodes.get(sender.name)
        if sender_node is None:
            raise ValueError(f"Sender node '{sender.name}' not found in graph '{self.name}'")
        if sender_node is not sender:
            raise ValueError(
                f"Sender node instance mismatch for '{sender.name}' in graph '{self.name}'"
            )

        receiver_node = self._nodes.get(receiver.name)
        if receiver_node is None:
            raise ValueError(f"Receiver node '{receiver.name}' not found in graph '{self.name}'")
        if receiver_node is not receiver:
            raise ValueError(
                f"Receiver node instance mismatch for '{receiver.name}' in graph '{self.name}'"
            )
        
        edge = Edge(sender, receiver, keys)

        cycle_path = self._check_cycle(edge)
        duplicate_edges = self._check_duplicate_edge(edge)
        error_message = ""
        if cycle_path:
            error_message += "Creating this edge would form a cycle in the graph:\n"
            current_node = edge.sender
            error_message += f" {current_node.name}"
            while True:
                if current_node not in cycle_path:
                    break
                next_edge = cycle_path[current_node]
                error_message += f" -> {next_edge.receiver.name}"
                current_node = next_edge.receiver
                if current_node == edge.sender:
                    break
            error_message += "\n\n"
        if duplicate_edges:
            error_message += f"{len(duplicate_edges)} duplicate edge occured:\n"
            for edge in duplicate_edges:
                error_message += edge.__str__() + "\n"
            error_message += "\n\n"
        if error_message:
            raise ValueError(error_message)
        
        sender.add_out_edge(edge)
        receiver.add_in_edge(edge)
        self._edges.append(edge)

        return edge

    def _is_loop_controller(self, node: Node) -> bool:
        return node.__class__.__name__ == "Controller"

    def _check_cycle(self, new_edge: Edge) -> dict[Node,Edge]|None:
        """
        Check whether `new_edge` creates a disallowed cycle.

        Cycles that pass through a loop controller are ignored.
        """
        start_node = new_edge.receiver
        target_node = new_edge.sender
        if start_node == target_node:
            if self._is_loop_controller(start_node):
                return None
            return {new_edge.sender: new_edge}
        visited = set()
        path = {}
        def dfs(node):
            visited.add(node)
            for edge in node.out_edges:
                next_node = edge.receiver
                if edge == new_edge:
                    continue
                if next_node == target_node:
                    cycle_dict = {}
                    cycle_dict[node] = edge
                    
                    current = node
                    while current != start_node:
                        prev_edge = path[current]
                        cycle_dict[prev_edge.sender] = prev_edge
                        current = prev_edge.sender
                    cycle_dict[target_node] = new_edge
                    for cycle_node in cycle_dict.keys():
                        if self._is_loop_controller(cycle_node):
                            return None
                    return cycle_dict
                if next_node not in visited:
                    path[next_node] = edge
                    result = dfs(next_node)
                    if result:
                        return result
            return None
        
        result = dfs(start_node)
        return result
        
    def _check_duplicate_edge(self, new_edge: Edge) -> list[Edge]|None:
        """Return existing edges with the same sender and receiver."""
        duplicate_edges = []
        sender = new_edge.sender
        receiver = new_edge.receiver
        for edge in sender.out_edges:
            if edge.receiver == receiver:
                duplicate_edges.append(edge)
        if len(duplicate_edges) > 0:
            return duplicate_edges
        else:
            return None
        
    def _check_duplicate_key(self, new_edge: Edge) -> dict[Edge, list[tuple[str]]]|None:
        """
        Check key collisions against other incoming edges of the receiver.

        Args:
            new_edge: Candidate edge.
        Returns:
            Mapping of conflicting edge to conflicting key paths.
        """
        duplicate_edges_keys_dict = {}
        receiver = new_edge.receiver

        def _recursive_check(
            d1: dict,
            d2: dict,
            current_path: tuple = (),
            conflicts: list[tuple[str]] | None = None,
        ):
            if conflicts is None:
                conflicts = []
            common_keys = d1.keys() & d2.keys()
            for key in common_keys:
                val1 = d1[key]
                val2 = d2[key]
                path = current_path + (key,)
                if isinstance(val1, dict) and isinstance(val2, dict):
                    _recursive_check(val1, val2, path, conflicts)
                else:
                    conflicts.append(path)
            return conflicts
        for in_edge in receiver.in_edges:
            conflicts = _recursive_check(new_edge.keys, in_edge.keys)
            if len(conflicts) > 0:
                duplicate_edges_keys_dict[in_edge] = conflicts
        if len(duplicate_edges_keys_dict) > 0:
            return duplicate_edges_keys_dict
        else:
            return None

    def reset(self):
        for node in self._nodes.values():
            node.reset()
        for edge in self._edges:
            edge.reset()
        super().reset()

    def reset_gate(self):
        """Reset graph gate and child runtime state."""
        for node in self._nodes.values():
            node.reset_gate()
        for edge in self._edges:
            edge.reset()
        super().reset_gate()

    def hook_register(
        self,
        hook_key: object,
        func: Callable,
        recursion: bool = False,
        target_type: type | tuple[type, ...] | None = None,
        target_names: str | set[str] | list[str] | tuple[str, ...] | Callable[[str], bool] | None = None,
        target_filter: Callable[[object], bool] | None = None,
        selector: Selector | None = None,
    ) -> None:
        """Register a hook callback and optionally recurse to children.

        Args:
            hook_key: Hook stage key (see `Node.Hook`).
            func: Hook callback function.
            recursion: If True, register the hook on child nodes and edges as well.
            target_type: Optional type filter used by the selector.
            target_names: Optional name filter (exact, set, list/tuple, predicate).
            target_filter: Optional predicate applied to the matched object.
            selector: Optional explicit selector. When provided, it overrides `target_type/target_names/target_filter`.
        """
        super().hook_register(
            hook_key,
            func,
            recursion=False,
            target_type=target_type,
            target_names=target_names,
            target_filter=target_filter,
            selector=selector,
        )
        if recursion:
            internal_nodes = list(self._iter_internal_nodes())

            seen: set[int] = set()
            for node in [*internal_nodes, *list(self._nodes.values())]:
                if id(node) in seen:
                    continue
                seen.add(id(node))
                node.hook_register(
                    hook_key,
                    func,
                    recursion=True,
                    target_type=target_type,
                    target_names=target_names,
                    target_filter=target_filter,
                    selector=selector,
                )
            for edge in self._edges:
                edge.hook_register(
                    hook_key,
                    func,
                    recursion=True,
                    target_type=target_type,
                    target_filter=target_filter,
                    selector=selector,
                )

    def _iter_internal_nodes(self) -> list[Node]:
        return []

    def _label_internal_node(self, node: Node) -> str | None:
        return None
