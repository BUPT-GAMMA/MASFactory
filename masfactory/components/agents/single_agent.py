from masfactory.core.gate import Gate
from masfactory.adapters.model import Model
from typing import Callable
from masfactory.components.agents.agent import Agent
from masfactory.adapters.memory import Memory
from masfactory.adapters.retrieval import Retrieval
class SingleAgent(Agent):
    """Convenience agent that can be invoked directly without graph wiring."""

    def __init__(
        self,
        name:str,
        model:Model,
        instructions:str|list[str],
        prompt_template:str|list[str]|None=None,
        max_retries:int=3,
        retry_delay:int=1,
        retry_backoff:int=2,
        tools:list[Callable]=None,
        memories:list[Memory]|None=None,
        retrievers:list[Retrieval]|None=None,   
        model_settings:dict|None=None,
        role_name=None,
    ):
        """Create a SingleAgent.

        Args:
            name: Node name.
            model: Model adapter used for invocation.
            instructions: System-level instructions for the agent.
            prompt_template: Optional user prompt template.
            max_retries: Max retries for model calls.
            retry_delay: Base delay multiplier for exponential backoff retries.
            retry_backoff: Exponential backoff base.
            tools: Optional tool callables available to the agent.
            memories: Optional memories attached to the agent.
            retrievers: Optional retrieval backends attached to the agent.
            model_settings: Provider/model settings passed into the adapter invoke call.
            role_name: Optional role label used in chat traces.
        """
        super().__init__(
            name=name,
            model=model,
            instructions=instructions,
            prompt_template=prompt_template, 
            tools=tools,
            memories=memories,
            retrievers=retrievers,
            model_settings=model_settings,
            role_name=role_name,
            max_retries=max_retries,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        )
        self._input = dict
        self._output = dict
        
    def _message_aggregate_in(self) -> dict[str,object]:
        return {"input":self._input}
        
    def _message_dispatch_out(self,message:dict[str,object]):
        self.output = message["output"]
        self._gate = Gate.OPEN

    def execute(self):
        """Execute one direct invocation round."""
        input = self.input
        output = self._forward(input)
        self.output = output

    def invoke(self,input:dict) -> object:
        """Run the agent directly and return output payload."""
        self.input = input
        self.execute()

        return self.output
