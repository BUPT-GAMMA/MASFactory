from __future__ import annotations
from typing import TYPE_CHECKING, Callable
from abc import ABC, abstractmethod
from .gate import Gate
from masfactory.utils.hook import masf_hook, HookManager, HookStage
from masfactory.utils.naming import validate_name
from masfactory.utils.selector import Selector, build_selector
if TYPE_CHECKING:
    from .edge import Edge
def merge_message(input:dict[str,object], message:dict[str,object]):
    for key in message.keys():
        if key in input.keys():
            input_val = input[key]
            message_val = message[key]
            if isinstance(input_val,list) and isinstance(message_val,list):
                input_val.extend(message_val)
            elif isinstance(input_val,dict) and isinstance(message_val,dict):
                input_val.update(message_val)
            elif isinstance(input_val,list) and not isinstance(message_val,list):
                input_val.append(message_val)
            else:
                input[key] = [input_val, message_val]
        else:
            input[key] = message[key]
    return input
class Node(ABC):
    """Base node type for MASFactory graphs.

    A node consumes attributes from an outer graph scope (via `pull_keys`), executes its core
    logic, and can push selected outputs back to the outer scope (via `push_keys`).

    Nodes also own inbound/outbound edges and expose a hook surface for instrumentation.
    """

    class Hook:
        EXECUTE = HookStage('execute')
        FORWARD = HookStage('forward')
        BUILD = HookStage('build')
        MESSAGE_AGGREGATE_IN = HookStage('message_aggregate_in')
        MESSAGE_DISPATCH_OUT = HookStage('message_dispatch_out')

    def __init__(self,
            name:str,
            pull_keys:dict[str,dict|str]|None=None,
            push_keys:dict[str,dict|str]|None=None,
            attributes:dict[str,object] | None = None,
            ):
        """
        Initialize a node.

        Args:
            name: Node name used in logs and graph lookups.
            pull_keys: Attribute keys pulled from the outer graph scope.
                - `None`: pull all outer attributes.
                - `{...}`: pull only listed keys.
                - `{}`: pull nothing.
            push_keys: Attribute keys pushed back after execution.
                - `None`: fallback to pull-key policy.
                - `{...}`: push only listed keys.
                - `{}`: push nothing.
            attributes: Local default attributes for this node.
        """
        if attributes is None:
            attributes = {}
        validate_name(name, kind="node name")
        self._in_edges:list[Edge] = []
        self._out_edges:list[Edge] = []
        self._name:str = name
        self._owner = None
        self._is_built:bool = False
        self._attributes_store:dict[str,object] = {}
        self._pull_keys:dict[str,dict|str]|None = pull_keys
        self._push_keys:dict[str,dict|str]|None = push_keys
        self._gate:Gate = Gate.OPEN
        self._hooks = HookManager()
        if pull_keys is None:
            key_gen_env = {}
        elif len(pull_keys) > 0:
            key_gen_env = {key:value for key,value in pull_keys.items()}
        elif len(pull_keys) == 0:
            key_gen_env = {}
        else:
            raise ValueError("pull_keys encountered an unexpected error")
        self._default_attributes = {**key_gen_env,**attributes} 
        self._attributes_store = self._default_attributes.copy()
    def _pull_attributes(self, outer_env:dict[str,object]|None):
        """Pull local attributes from `outer_env` according to `pull_keys`."""
        if outer_env:
            if self._pull_keys is None:
                self._attributes_store = {**self._attributes_store,**outer_env.copy()}
            elif len(self._pull_keys) > 0:
                self._update_env(self._attributes_store, outer_env, self._pull_keys)
            elif len(self._pull_keys) == 0:
                pass
            else:
                raise ValueError("pull_keys encountered an unexpected error")

    def _attributes_push_local(self, update_env:dict[str,object]|None):
        """Push output fields to local attributes according to `push_keys`."""
        if update_env:
            if self._push_keys is None:
                if self._pull_keys is not None:
                    self._update_env(self._attributes_store, update_env, self._pull_keys)
                else:
                    self._update_env(self._attributes_store, update_env, None)
            elif len(self._push_keys) == 0:
                pass
            elif len(self._push_keys) > 0:
                self._update_env(self._attributes_store, update_env, self._push_keys)
            else:
                raise ValueError("push_keys encountered an unexpected error")

    def _attributes_push_outer(self,outer_env:dict[str,object]|None, update_env:dict[str,object]|None):
        """Push output fields to outer attributes according to `push_keys`."""
        if update_env is not None and outer_env is not None: 
            if self._push_keys is None:
                if self._pull_keys is not None:
                    self._update_env(outer_env, update_env, self._pull_keys)
                else:
                    self._update_env(outer_env, update_env, None)
            elif len(self._push_keys) == 0:
                pass
            elif len(self._push_keys) > 0:
                self._update_env(outer_env, update_env, self._push_keys)
            else:
                raise ValueError("push_keys encountered an unexpected error")

    def _update_env(self, updated_env:dict[str,object], update_env:dict[str,object], update_keys:dict[str,str]|None):
        """Update selected keys from `update_env` into `updated_env`."""
        if update_env is None:
            raise ValueError("update_env must not be None")
        if updated_env is None:
            raise ValueError("updated_env must not be None")

        if update_keys is not None:
            for key in update_keys.keys():
                if key in update_env.keys():
                    updated_env[key] = update_env[key]
        elif updated_env is not None and update_env is not None:
            common_keys = set(updated_env.keys()) & set(update_env.keys())
            for key in common_keys:
                updated_env[key] = update_env[key]
        return updated_env
    @property
    def name(self) -> str:
        return self._name

    @property
    def owner(self) -> "Node | None":
        """Return the graph node that owns this node, if any."""
        return self._owner

    def _set_owner(self, owner: "Node | None") -> None:
        self._owner = owner

    @property
    def pull_keys(self) -> dict[str, dict | str] | None:
        """
        Read-only view of this node's `pull_keys` rule.
        """
        if self._pull_keys is None:
            return None
        return self._pull_keys.copy()

    @property
    def push_keys(self) -> dict[str, dict | str] | None:
        """
        Read-only view of this node's `push_keys` rule.
        """
        if self._push_keys is None:
            return None
        return self._push_keys.copy()
    @property
    def attributes(self):
        return self._attributes_store
    @property
    def in_edges(self) -> list[Edge]:
        return self._in_edges.copy()
        
    @property
    def out_edges(self) -> list[Edge]:
        return self._out_edges.copy()
        
    @property
    def input_keys(self) -> dict[str,dict|str]:
        merged_keys = {}
        for edge in self._in_edges:
            merged_keys.update(edge.keys)
        return merged_keys
        
    @property
    def output_keys(self) -> dict[str,dict|str]:
        merged_keys = {}
        for edge in self._out_edges:
            merged_keys.update(edge.keys)
        return merged_keys

    def add_in_edge(self, edge):
        self._in_edges.append(edge)

    def add_out_edge(self, edge):
        self._out_edges.append(edge)
        
    @property
    def is_ready(self) -> bool:
        for in_edge in self.in_edges:
            if not in_edge.is_congested and in_edge.gate == Gate.OPEN:
                return False
        return True
    
    def _update_gate_state(self):
        """Update node gate from incoming edge gates."""
        for in_edge in self.in_edges:
            if in_edge.gate == Gate.OPEN:
                self._gate = Gate.OPEN
                return
        self._gate = Gate.CLOSED
    @masf_hook(Hook.MESSAGE_AGGREGATE_IN)
    def _message_aggregate_in(self) -> dict[str,object]:
        """Merge messages from all open incoming edges."""
        input = dict()
        for in_edge in self.in_edges:
            if in_edge.gate == Gate.CLOSED:
                continue
            if in_edge.is_congested:
                message:dict[str,object] = in_edge.receive_message()
                input = merge_message(input, message)
        return input
    @masf_hook(Hook.MESSAGE_DISPATCH_OUT)
    def _message_dispatch_out(self, message:dict[str,object]):
        """Dispatch one message to all outgoing edges."""
        for out_edge in self.out_edges:
            out_edge.send_message(message)
        self._gate = Gate.OPEN

    def _close_out_edges(self):
        """Close all outgoing edges."""
        for out_edge in self.out_edges:
            out_edge.close()
    def _reset_gate_state(self):
        """Reset node gate and all incoming edge gates to open."""
        self._gate = Gate.OPEN
        for in_edge in self.in_edges:
            in_edge.open()
    @masf_hook(Hook.EXECUTE)
    def execute(self, outer_env:dict[str,object]|None=None):
        """Execute one node step."""
        self._update_gate_state()
        if self.gate == Gate.OPEN:
            self._pull_attributes(outer_env)
            input:dict = self._message_aggregate_in()
            output:dict = self._forward(input)
            self._update_gate_state()
            # Always push output to local attributes, even if there are no out_edges
            # This ensures that _attributes_push_outer can push the correct data to outer_env
            self._attributes_push_local(output)
            self._attributes_push_outer(outer_env, self._attributes_store)
            if self.gate == Gate.CLOSED:
                self._close_out_edges()
                return
            self._message_dispatch_out(output)

        else:
            self._close_out_edges()
        self._reset_gate_state()

    @abstractmethod
    @masf_hook(Hook.FORWARD)
    def _forward(self, input:dict[str,object]) -> dict[str,object]:
        """
        Args:
            input (dict[str,object]): Node input payload.
        Returns:
            dict[str,object]: Node output payload.
            
        Raises:
            NotImplementedError: Subclasses must implement this method.
        """
        raise NotImplementedError("Subclasses must implement this method")
    
    def check_built(self) -> bool:
        return self._is_built
    @masf_hook(Hook.BUILD)
    def build(self):
        self._is_built = True
    
    def __str__(self):
        return f"Node {self.name} with input keys {self.input_keys} and output keys {self.output_keys}  "
    def set_pull_keys(self,pull_keys:dict[str,dict|str]|None):
        """Update this node's attribute pull policy.

        Args:
            pull_keys: Attribute keys pulled from the outer graph scope.
                - `None`: pull all outer attributes.
                - `{...}`: pull only listed keys.
                - `{}`: pull nothing.

        Notes:
            This updates the policy used by future `execute()` calls. It does not rebuild
            existing local attributes.
        """
        self._pull_keys = pull_keys
    def set_push_keys(self,push_keys:dict[str,dict|str]|None):
        """Update this node's attribute push policy.

        Args:
            push_keys: Attribute keys pushed back after execution.
                - `None`: fallback to pull-key policy.
                - `{...}`: push only listed keys.
                - `{}`: push nothing.

        Notes:
            This updates the policy used by future `execute()` calls. It does not rebuild
            existing local attributes.
        """
        self._push_keys = push_keys
    def set_attributes(self,attributes:dict[str,object]):
        if attributes is None:
            raise ValueError("attributes must not be None")
        self._default_attributes = {**self._default_attributes,**attributes}
    def reset(self):
        self.reset_gate()
        self.reset_attributes()
    @property
    def gate(self) -> Gate:
        return self._gate
    @property
    def hooks(self) -> HookManager:
        return self._hooks

    def reset_attributes(self):
        self._attributes_store = self._default_attributes.copy()

    def reset_gate(self):
        self._gate = Gate.OPEN
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
        """Register a hook callback on this node.

        Args:
            hook_key: Hook stage key (see `Node.Hook`).
            func: Hook callback function.
            recursion: Reserved for API parity. Recursion is implemented by graphs/edges; a plain
                Node does not recurse into children.
            target_type: Optional type filter used by the selector.
            target_names: Optional name filter (exact, set, list/tuple, predicate).
            target_filter: Optional predicate applied to the matched object.
            selector: Optional explicit selector. When provided, it overrides `target_type/target_names/target_filter`.
        """
        # Use Node as the default selector type.
        if target_type is None:
            target_type = Node
        predicate = None
        if target_filter is not None:
            predicate = lambda t: t.obj is not None and target_filter(t.obj)

        selector = build_selector(
            selector=selector,
            type_filter=target_type,
            name_filter=target_names,
            predicate=predicate,
        )
        if selector.match(self):
            self._hooks.register(hook_key, func)
