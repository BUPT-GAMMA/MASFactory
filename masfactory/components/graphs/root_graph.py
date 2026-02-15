from masfactory.core.node import Gate
from masfactory.components.graphs.graph import Graph
from masfactory.core.node_template import NodeTemplate

class RootGraph(Graph):
    """
    Top-level executable graph.

    RootGraph is the user-facing entry point for building and invoking workflows.
    """
    def __init__(
        self,
        name: str,
        attributes: dict[str, object] | None = None,
        edges: list[tuple[str, str] | tuple[str, str, dict[str, dict|str] ]]|None=None,
        nodes: list[tuple[str,NodeTemplate]] | None = None,
    ):
        """Create a RootGraph.

        Args:
            name: Graph name.
            attributes: Default attributes for this graph.
            edges: Optional declarative edge definitions (see `Graph.__init__`).
            nodes: Optional declarative node definitions (see `Graph.__init__`).
        """
        super().__init__(name=name, attributes=attributes, edges=edges, nodes=nodes)
        self._input = {}
        self._output = {}
    
    def invoke(self, input: dict, attributes: dict[str, object] | None = None):
        """
        Execute the root graph.

        Args:
            input: Graph input payload.
            attributes: Optional attribute overrides for this invocation.

        Returns:
            tuple[dict, dict[str, object]]: `(output, attributes_snapshot)`.
        """
        if not self.check_built():
            raise RuntimeError("Graph is not built yet. Please build the graph first.")
        if attributes is None:
            attributes = {}
        self._attributes_store = {**self._attributes_store, **attributes}
        try:
            from masfactory.visualizer import get_bridge  # noqa: WPS433
        except Exception:
            get_bridge = None  # type: ignore[assignment]
        runtime = get_bridge() if get_bridge is not None else None
        if runtime is not None:
            runtime.begin_run(self, input=input)
        self._input = input
        self.execute(self.attributes)
        if runtime is not None:
            runtime.end_run(self, output=self._output if isinstance(self._output, dict) else None)
        return self._output,self.attributes.copy()

    def build(self):
        if self._is_built:
            return
        super().build()
        try:
            from masfactory.visualizer import get_bridge  # noqa: WPS433
        except Exception:
            get_bridge = None  # type: ignore[assignment]
        runtime = get_bridge() if get_bridge is not None else None
        if runtime is not None:
            runtime.attach_graph(self)
    def _update_gate_state(self):
        pass
    def _message_aggregate_in(self) -> dict[str,object]:
        return self._input
    
    def _message_dispatch_out(self, message:dict[str,object]):
        self._output = message
        self._gate = Gate.OPEN
    
