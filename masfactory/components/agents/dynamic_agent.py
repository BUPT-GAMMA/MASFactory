from masfactory.adapters.model import Model
from typing import Callable
from masfactory.components.agents.agent import Agent
from masfactory.adapters.memory import Memory
from masfactory.adapters.retrieval import Retrieval
from masfactory.core.message import MessageFormatter
from masfactory.core.node import Node
from masfactory.utils.hook import masf_hook

_UNSET = object()
class DynamicAgent(Agent):
    """Agent variant that updates instructions from each input message."""

    def __init__(self, name:str,
        model:Model, 
        default_instructions:str="",
        tools:list[Callable]=None,
        formatters:list[MessageFormatter]|MessageFormatter=None,
        max_retries:int=3,
        retry_delay:int=1,
        retry_backoff:int=2,
        pull_keys:dict[str,dict|str]|None|object=_UNSET,
        push_keys:dict[str,dict|str]|None|object=_UNSET,
        instruction_key:str="instructions",
        role_name:str=None,
        prompt_template:str=None,
        model_settings:dict[str,str]=None,
        memories:list[Memory]=None,
        retrievers:list[Retrieval]=None,
        attributes:dict[str, object] | None = None
        ):
        """Create a DynamicAgent.

        Args:
            name: Node name.
            model: Model adapter used for invocation.
            default_instructions: Initial instructions used when no override is provided.
            tools: Optional tool callables available to the agent.
            formatters: Message formatter(s) passed to the base Agent.
            max_retries: Max retries for model calls.
            retry_delay: Base delay multiplier for exponential backoff retries.
            retry_backoff: Exponential backoff base.
            pull_keys: Pull key policy for attributes.
            push_keys: Push key policy for attributes.
            instruction_key: Input field name used to override `instructions` at runtime.
            role_name: Optional role label used in chat traces.
            prompt_template: Optional user prompt template.
            model_settings: Provider/model settings passed into the adapter invoke call.
            memories: Optional memories attached to the agent.
            retrievers: Optional retrieval backends attached to the agent.
            attributes: Optional default attributes local to this agent.
        """
        if pull_keys is _UNSET:
            pull_keys = {}
        if push_keys is _UNSET:
            push_keys = {}
        if attributes is None:
            attributes = {}
        
        super().__init__(
            name=name,
            model=model,
            instructions=default_instructions,
            prompt_template=prompt_template,
            tools=tools,
            memories=memories,
            retrievers=retrievers,
            pull_keys=pull_keys,
            push_keys=push_keys,
            model_settings=model_settings,
            role_name=role_name,
            formatters=formatters,
            max_retries=max_retries,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
            attributes=attributes
        )
        self._instruction_key = instruction_key

    @masf_hook(Node.Hook.FORWARD)
    def _forward(self, input_dict:dict[str,object]) -> dict[str,object]:
        """Update instructions from `instruction_key`, then run parent forward."""
        self._instructions = input_dict[self._instruction_key]
        input_dict.pop(self._instruction_key)
        return super()._forward(input_dict)
        
