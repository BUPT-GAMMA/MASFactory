from masfactory.core.node import Node,Gate
from typing import Callable
from masfactory.utils.hook import masf_hook
class InternalGraphNode(Node):
    """
    Base class for internal graph control nodes.

    This class is used by `EntryNode`, `ExitNode`, `Controller`, and `TerminateNode`.
    """
    def __init__(
        self, 
        name, 
        gate_close_callback: Callable|None = None, 
        pull_keys: dict[str, dict|str]|None = None, 
        push_keys: dict[str, dict|str]|None = None, 
        attributes: dict[str, object] | None = None
    ):
        """Create an internal control node.

        Args:
            name: Node name.
            gate_close_callback: Optional callback invoked when this node closes its gate.
            pull_keys: Attribute pull rule for this node.
            push_keys: Attribute push rule for this node.
            attributes: Optional default attributes local to this node.
        """
        super().__init__(name, pull_keys, push_keys, attributes)
        self.input: dict[str, object] = {}
        self._gate_close_callback = gate_close_callback
        self._output: dict[str, object] = {}
        self._is_terminated:bool = True
    @property
    def output(self) -> dict[str, object]:
        return self._output

    def _message_dispatch_out(self,message:dict[str,object]):
        for out_edge in self.out_edges:
            out_edge.send_message(message)
        self._gate = Gate.OPEN
    def _close_out_edges(self):
        if self._gate_close_callback is not None:
            self._gate_close_callback()
    def execute(self, outer_env:dict[str,object]|None=None):
        """Execute one control-node step.

        Internal control nodes differ from regular nodes:
        - They do not dispatch via Edge.gate semantics for every outgoing edge; instead they
          either invoke the graph-level close callback or dispatch a single message payload.
        - They always propagate attribute changes back to `outer_env` before returning.

        Args:
            outer_env: Optional outer attribute dict provided by the owning graph.
        """
        self._update_gate_state()
        if self.gate == Gate.CLOSED:
            self._close_out_edges()
            return
        self._pull_attributes(outer_env)
        input = self._message_aggregate_in()
        output_val = self._forward(input)
        if self.gate == Gate.CLOSED:
            self._close_out_edges()
            self._attributes_push_outer(outer_env, self._attributes_store)
            return
        self._message_dispatch_out(output_val)
        self._attributes_push_outer(outer_env, self._attributes_store)
        self._reset_gate_state()

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        self._is_built = True
