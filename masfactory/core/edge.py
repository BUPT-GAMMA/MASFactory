from __future__ import annotations
from typing import TYPE_CHECKING, Callable

from masfactory.utils.hook import HookManager
from masfactory.utils.selector import Selector, build_selector

from .gate import Gate
if TYPE_CHECKING:
    from .node import Node

class Edge:
    """Directed message channel between two nodes.

    An `Edge` buffers at most one in-flight message at a time. It can be opened/closed via a
    gate, and it becomes *congested* when a message is pending consumption by the receiver.
    """
    
    class Hook:
        SEND_MESSAGE = 'send_message'
        RECEIVE_MESSAGE = 'receive_message'
    def __init__(self,
            sender:Node,
            receiver:Node,
            keys:dict[str,dict|str]|None=None):
        """
        Args:
            sender: Source node.
            receiver: Target node.
            keys: Message fields forwarded by this edge.
        """
        self._sender:Node = sender
        self._receiver:Node = receiver
        self._keys:dict[str,dict|str] = keys if keys is not None else {"message":""}
        self._message:dict = {}
        self._is_congested:bool = False
        self._gate:Gate = Gate.OPEN
        self._hooks = HookManager()
    @property
    def hooks(self) -> HookManager:
        return self._hooks
    def hook_register(
        self,
        hook_key: object,
        func: Callable,
        recursion: bool = False,
        target_type: type | tuple[type, ...] | None = None,
        target_filter: Callable[[object], bool] | None = None,
        selector: Selector | None = None,
    ) -> None:
        """
        Register edge hooks with selector filtering.

        Edge objects do not support name filtering.

        Args:
            hook_key: Hook stage key.
            func: Hook callback function.
            recursion: Reserved for API parity. Recursion is implemented by graphs.
            target_type: Optional type filter used by the selector.
            target_filter: Optional predicate applied to the matched object.
            selector: Optional explicit selector. When provided, it overrides `target_type/target_filter`.
        """
        predicate = None
        if target_filter is not None:
            predicate = lambda t: t.obj is not None and target_filter(t.obj)

        selector = build_selector(
            selector=selector,
            type_filter=target_type,
            predicate=predicate,
        )
        if selector.match(self):
            self._hooks.register(hook_key, func)

    def __str__(self):
        return f"Edge from {self._sender.name} to {self._receiver.name} with keys {self._keys}"

    @property
    def sender(self) -> "Node":
        return self._sender

    @property
    def receiver(self) -> "Node":
        return self._receiver
    
    def send_message(self, message:dict):
        """
        Send a message through the edge.

        Args:
            message: Message payload.
        Raises:
            RuntimeError: Edge still has an unconsumed message.
            KeyError: Message misses required keys.
        """
        if self.is_congested:
            raise RuntimeError(
                "Edge is congested, please wait for the message to be received."
            )

        missing_keys = [key for key in self.keys if key not in message]
        if missing_keys:
            raise KeyError(f"Missing keys {missing_keys} for {self}")

        self._message = {key: message[key] for key in self.keys}
        self._hooks.dispatch(self.Hook.SEND_MESSAGE,self._sender,self._receiver, message)

        self._is_congested = True
        self._gate = Gate.OPEN

    def receive_message(self) -> dict:
        """
        Receive and clear the current message.

        Returns:
            dict: Received payload.

        Raises:
            RuntimeError: No pending message exists on the edge.
        """
        if not self.is_congested:
            raise RuntimeError("No message to receive, please send a message first.")
        self._hooks.dispatch(self.Hook.RECEIVE_MESSAGE,self._sender,self._receiver, self._message)
        message = self._message.copy()
        self._is_congested = False
        self._message = {}

        return message

    @property
    def keys(self) -> dict[str,dict|str]:
        return self._keys

    @property
    def is_congested(self) -> bool:
        return self._is_congested

    @property
    def gate(self) -> Gate:
        return self._gate
    
    def close(self):
        self._gate = Gate.CLOSED
    
    def open(self):
        self._gate = Gate.OPEN
    def reset(self):
        self._message = {}
        self._is_congested = False
        self._gate = Gate.OPEN
    def reset_gate(self):
        self._gate = Gate.OPEN
