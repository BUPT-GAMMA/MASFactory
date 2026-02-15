from __future__ import annotations
import inspect
from typing import Callable
from masfactory.adapters.memory import Memory
from masfactory.core.node import Node
from masfactory.adapters.retrieval import Retrieval
from masfactory.utils.hook import masf_hook

class CustomNode(Node):
    """Node wrapper around a user-provided Python callable."""

    def __init__(self,
            name,
            forward:Callable[...,dict[str,object]]|None=None,
            memories:list[Memory]|None=None,
            tools:list[Callable]|None=None,
            retrievers:list[Retrieval]|None=None,
            pull_keys:dict[str,dict|str]|None=None,
            push_keys:dict[str,dict|str]|None=None,
            attributes:dict[str,object] | None = None):
        """Create a CustomNode.

        Args:
            name: Node name.
            forward: Optional callable implementing node logic. Supported signatures are:
                - `(input) -> output`
                - `(input, attributes) -> output`
                - `(input, attributes, memories) -> output`
                - `(input, attributes, memories, tools) -> output`
                - `(input, attributes, memories, tools, retrievers) -> output`
                - `(input, attributes, memories, tools, retrievers, node) -> output`

                Where:
                - `input`: `dict[str, object]`
                - `attributes`: `dict[str, object]` (node-local attribute store)
                - `memories`: `list[Memory] | None`
                - `tools`: `list[Callable] | None`
                - `retrievers`: `list[Retrieval] | None`
                - `node`: `CustomNode`
                - `output`: `dict[str, object]`
            memories: Optional memories passed to the forward callable.
            tools: Optional tool callables passed to the forward callable.
            retrievers: Optional retrieval backends passed to the forward callable.
            pull_keys: Attribute pull rule for this node.
            push_keys: Attribute push rule for this node.
            attributes: Optional default attributes local to this node.
        """
        super().__init__(name, pull_keys, push_keys, attributes)
        self._forward_function = forward
        self._memories = memories
        self._tools = tools
        self._retrievers = retrievers
    def set_forward(self,forward:Callable[...,dict[str,object]]):
        """Set the user forward callable used by this CustomNode.

        Args:
            forward: Callable implementing node logic. Supported signatures are:
                - `(input) -> output`
                - `(input, attributes) -> output`
                - `(input, attributes, memories) -> output`
                - `(input, attributes, memories, tools) -> output`
                - `(input, attributes, memories, tools, retrievers) -> output`
                - `(input, attributes, memories, tools, retrievers, node) -> output`

                Where `input` and `output` are `dict[str, object]`.
        """
        self._forward_function = forward

    @masf_hook(Node.Hook.FORWARD)
    def _forward(self,input:dict[str,object]):
        """Dispatch to the configured forward callable.

        Args:
            input: Node input payload.

        Returns:
            Node output payload returned by the forward callable.

        Raises:
            ValueError: If the forward callable has an unsupported parameter count.
            TypeError: If the forward callable does not return a dict payload.
        """
        if not self._forward_function:
            return input
        param_count = len(inspect.signature(self._forward_function).parameters)
        if param_count == 1:
            result = self._forward_function(input)
        elif param_count == 2:
            result = self._forward_function(input, self._attributes_store)
        elif param_count == 3:
            result = self._forward_function(input, self._attributes_store, self._memories)
        elif param_count == 4:
            result = self._forward_function(input, self._attributes_store, self._memories, self._tools)
        elif param_count == 5:
            result = self._forward_function(
                input, self._attributes_store, self._memories, self._tools, self._retrievers
            )
        elif param_count == 6:
            result = self._forward_function(
                input,
                self._attributes_store,
                self._memories,
                self._tools,
                self._retrievers,
                self,
            )
        else:
            raise ValueError('forward must have 1..6 parameters')
        if not isinstance(result, dict):
            raise TypeError(
                f"CustomNode forward function must return a dict, got {type(result)}"
            )
        return result
