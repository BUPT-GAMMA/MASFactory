from masfactory.components.agents.agent import Agent
from masfactory.components.graphs.loop import Loop
from masfactory.components.controls.logic_switch import LogicSwitch
from masfactory.adapters.memory import Memory,HistoryMemory
from masfactory.adapters.model import Model
from masfactory.core.message import MessageFormatter
from masfactory.utils.hook import masf_hook
from masfactory.core.node import Node
from typing import Callable, List

class InstructorAssistantGraph(Loop):
    """A two-agent alternating loop: instructor <-> assistant.

    The loop controller routes each iteration to either the instructor or assistant agent via an
    internal LogicSwitch. Each agent's output flows back to the controller, enabling multi-turn
    collaboration patterns like planning + implementation or critique + refinement.
    """

    def __init__(self, 
                 name,
                 instructor_role_name: str,
                 instructor_instructions: list | str,
                 assistant_role_name: str,
                 assistant_instructions: list | str,
                 phase_instructions: list | str,
                 model: Model,
                 max_turns: int,
                 instructor_prompt_template: str|None = None,
                 assistant_prompt_template: str|None = None,
                 assistant_in_keys: dict[str, str] | None = None,
                 assistant_out_keys: dict[str, str] | None = None,
                 instructor_in_keys: dict[str, str] | None = None,
                 instructor_out_keys: dict[str, str] | None = None,
                 instructor_first: bool = True,
                 instructor_memories: list[Memory] | Memory | None = None,
                 assistant_memories: list[Memory] | Memory | None = None,
                 instructor_tools: List[Callable] | None = None,
                 assistant_tools: List[Callable] | None = None, 
                 terminate_condition_prompt: str | None = None,
                 terminate_condition_function: Callable | None = None,
                 formatters: MessageFormatter | None = None,
                 pull_keys: dict[str, dict|str] | None = None,
                 push_keys: dict[str, dict|str] | None = None,
                 attributes: dict[str, object] | None = None,
                 agent_model_settings: dict | None = None):
        """Create an InstructorAssistantGraph.

        Args:
            name: Graph name.
            instructor_role_name: Role name for the instructor agent.
            instructor_instructions: Instructions for the instructor agent.
            assistant_role_name: Role name for the assistant agent.
            assistant_instructions: Instructions for the assistant agent.
            phase_instructions: Shared phase instructions that can be appended by the agent implementation.
            model: Model adapter used by both agents.
            max_turns: Maximum number of loop iterations.
            instructor_prompt_template: Optional prompt template for the instructor agent.
            assistant_prompt_template: Optional prompt template for the assistant agent.
            assistant_in_keys: Keys from controller -> assistant. Defaults are inferred from the opposite side.
            assistant_out_keys: Keys from assistant -> controller. Defaults are inferred from the opposite side.
            instructor_in_keys: Keys from controller -> instructor. Defaults are inferred from the opposite side.
            instructor_out_keys: Keys from instructor -> controller. Defaults are inferred from the opposite side.
            instructor_first: If True, instructor runs on the first iteration (iteration=1).
            instructor_memories: Memories used by the instructor agent (HistoryMemory is always appended).
            assistant_memories: Memories used by the assistant agent (HistoryMemory is always appended).
            instructor_tools: Tools available to the instructor agent.
            assistant_tools: Tools available to the assistant agent.
            terminate_condition_prompt: Optional natural language termination condition.
            terminate_condition_function: Optional loop termination predicate.
            formatters: Optional message formatter(s) used by agents.
            pull_keys: Attribute pull rule for this loop graph.
            push_keys: Attribute push rule for this loop graph.
            attributes: Default attributes for this loop graph.
            agent_model_settings: Optional provider/model settings passed into agents.
        """
        if attributes is None:
            attributes = {}
        super().__init__(name=name,
                         pull_keys=pull_keys,
                         push_keys=push_keys,
                         max_iterations=max_turns,
                         terminate_condition_prompt=terminate_condition_prompt,
                         terminate_condition_function=terminate_condition_function,
                         attributes=attributes)
        self._instructor_role_name = instructor_role_name
        self._instructor_instructions = instructor_instructions
        self._assistant_role_name = assistant_role_name
        self._assistant_instructions = assistant_instructions
        self._assistant_prompt_template = assistant_prompt_template
        self._instructor_prompt_template = instructor_prompt_template
        self._phase_instructions = phase_instructions
        self._model = model
        self._instructor_chat_history = HistoryMemory(top_k=100,memory_size=10000)
        self._assistant_chat_history = HistoryMemory(top_k=100,memory_size=10000)
        self._instructor = None
        self._assistant = None
        if instructor_memories is None:
            instructor_memories = []
        if assistant_memories is None:
            assistant_memories = []
        if isinstance(instructor_memories, Memory):
            instructor_memories = [instructor_memories]
        if isinstance(assistant_memories, Memory):
            assistant_memories = [assistant_memories]
        self._instructor_memories = [*instructor_memories,self._instructor_chat_history]
        self._assistant_memories = [*assistant_memories,self._assistant_chat_history]
        self._assistant_tools = assistant_tools or []  
        self._instructor_tools = instructor_tools or []
        self._formatters = formatters
        self._agent_model_settings = dict(agent_model_settings) if agent_model_settings else None
        self._assistant_in_keys = assistant_in_keys if assistant_in_keys else instructor_out_keys if instructor_out_keys else self.input_keys
        self._assistant_out_keys = assistant_out_keys if assistant_out_keys else instructor_in_keys if instructor_in_keys else self.output_keys
        self._instructor_in_keys = instructor_in_keys if instructor_in_keys else assistant_out_keys if assistant_out_keys else self.input_keys
        self._instructor_out_keys = instructor_out_keys if instructor_out_keys else assistant_in_keys if assistant_in_keys else self.output_keys
        self._instructor_first = instructor_first
    @property
    def instructor_chat_history(self) -> HistoryMemory:
        return self._instructor_chat_history

    @property
    def assistant_chat_history(self) -> HistoryMemory:
        return self._assistant_chat_history

    @masf_hook(Node.Hook.BUILD) 
    def build(self):
        """Build the internal agents and switch routing for the loop."""
        self._instructor = self.create_node(
            Agent,
            name=self.name + "_instructor",   
            role_name=self._instructor_role_name,    
            instructions=self._instructor_instructions, 
            prompt_template=self._instructor_prompt_template, 
            memories=self._instructor_memories,
            model=self._model,
            model_settings=self._agent_model_settings,
            tools=self._instructor_tools,
            formatters=self._formatters,
            pull_keys=self._pull_keys,
            push_keys=self._push_keys 
        )
        self._assistant: Agent = self.create_node(
            Agent,  
            name=self.name + "_assistant", 
            role_name=self._assistant_role_name,
            instructions=self._assistant_instructions,
            prompt_template=self._assistant_prompt_template,
            memories=self._assistant_memories,
            model=self._model,
            model_settings=self._agent_model_settings,
            tools=self._assistant_tools,
            formatters=self._formatters,
            pull_keys=self._pull_keys,
            push_keys=self._push_keys
        )

        switch_node:LogicSwitch = self.create_node(
            LogicSwitch,
            name=self.name + "_switch",
        ) 
        
        self.edge_from_controller(
            receiver=switch_node,
            keys={**self._instructor_in_keys,**self._assistant_in_keys}
        )
        edge_switch_to_instructor = self.create_edge(
            sender=switch_node,
            receiver=self._instructor,
            keys=self._instructor_in_keys
        )
        edge_switch_to_assistant = self.create_edge(
            sender=switch_node,
            receiver=self._assistant,
            keys=self._assistant_in_keys
        )
        self.edge_to_controller(
            sender=self._instructor,
            keys=self._instructor_out_keys
        )
        self.edge_to_controller(
            sender=self._assistant,
            keys=self._assistant_out_keys
        )
        def switch_to_instructor(message:dict, attributes:dict[str,object]) -> bool:
            current_iteration = attributes.get("current_iteration", 0)            
            return current_iteration % 2 == 1 if self._instructor_first else current_iteration % 2 == 0
        
        def switch_to_assistant(message:dict, attributes:dict[str,object]) -> bool:
            current_iteration = attributes.get("current_iteration", 0)
            return current_iteration % 2 == 0 if self._instructor_first else current_iteration % 2 == 1
        
        switch_node.condition_binding(switch_to_instructor,edge_switch_to_instructor)
        switch_node.condition_binding(switch_to_assistant,edge_switch_to_assistant)
        super().build()
