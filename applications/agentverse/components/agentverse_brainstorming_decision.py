from masfactory import Graph, Agent, Model, Memory, CustomNode, Node
from masfactory import HistoryMemory
from masfactory import HorizontalGraph
from masfactory import BrainstormingGraph
from masfactory.utils.hook import masf_hook

class AgentverseBrainstormingDecisionGraph(Graph):
    """Brainstorming-style decision graph wrapper.

    Runs multiple critics and then a summarizer. Uses a shared HistoryMemory and
    does not clear it automatically.
    """
    
    def __init__(
        self,
        name: str,
        solver_role_name: str,
        solver_instructions: str | list[str],
        critic_configs: list[dict],
        model: Model,
        summarize_discussion: bool = True,
        solver_memories: list[Memory] | Memory | None = None,
        critic_memories: list[Memory] | Memory | None = None,
        pull_keys: dict[str, str] | None = None,
        push_keys: dict[str, str] | None = None,
        attributes: dict[str, object] | None = None,
    ):
        super().__init__(name, pull_keys, push_keys, attributes)
        
        self._solver_role_name = solver_role_name
        self._solver_instructions = solver_instructions
        self._critic_configs = critic_configs
        self._model = model
        self._summarize_discussion = summarize_discussion
        
        # Shared chat history across all agents in this graph.
        self._shared_history = HistoryMemory(top_k=100, memory_size=10000)
        
        # Normalize memory inputs.
        if solver_memories is None:
            solver_memories = []
        if critic_memories is None:
            critic_memories = []
        if isinstance(solver_memories, Memory):
            solver_memories = [solver_memories]
        if isinstance(critic_memories, Memory):
            critic_memories = [critic_memories]
            
        self._solver_memories = [*solver_memories, self._shared_history]
        self._critic_memories = [*critic_memories, self._shared_history]
        
        # Agents are created in build().
        self._solver = None
        self._critics = []
        self._memory_manager = None
    
    @property
    def shared_history(self) -> HistoryMemory:
        return self._shared_history
    
    @masf_hook(Node.Hook.BUILD)
    def build(self):
        # Set default pull/push keys if not provided.
        if self._pull_keys is None:
            self._pull_keys = {
                "task_description": "Task to solve",
                "previous_plan": "Previous solution (if any)",
                "advice": "Advice from evaluator (if any)",
            }
        
        if self._push_keys is None:
            self._push_keys = {
                "solution": "Generated solution"
            }
        
        # Build critic agent args.
        critics_args = []
        for i, critic_config in enumerate(self._critic_configs):
            critics_args.append(
                {
                    "cls":Agent,
                    "name":f"{self.name}_critic_{i}",
                    "role_name":critic_config.get("role_name", f"Critic {i+1}"),
                    "instructions":critic_config.get("instructions", "Provide critical feedback."),
                    "memories":self._critic_memories,
                    "model":self._model,
                    "pull_keys":{
                        "task_description": "The task to solve",
                        "previous_plan": "The previous plan",
                        "advice": "The advice",
                        "role_description": "The description of the role",
                        "broadcast": "No broadcast message yet."
                    },
                    "push_keys":{"advice_{}".format(i): "The advice of you."} 
                }
            )
        
        # Build summarizer agent args.
        summarizer_instructions = self._solver_instructions
        if self._summarize_discussion:
            if isinstance(summarizer_instructions, list):
                summarizer_instructions = list(summarizer_instructions)
                summarizer_instructions.append(
                    "After reviewing all feedback, provide a comprehensive summary of the discussion, "
                    "capturing key points and insights."
                )
            else:
                summarizer_instructions = (
                    f"{summarizer_instructions}\n\n"
                    "After reviewing all feedback, provide a comprehensive summary of the discussion, "
                    "capturing key points and insights."
                )
        
        solver_args = {
            "cls":Agent,
            "name":f"{self.name}_summarizer",
            "role_name":self._solver_role_name,
            "instructions":summarizer_instructions,
            "memories":self._solver_memories,
            "model":self._model,
            "pull_keys":{
                "task_description": "The task to solve",
                "previous_plan": "The previous plan",
                "advice": "The advice",
                "role_description": "The description of the role",
                "broadcast": "The broadcast message"
            },
            "push_keys":{
                "solution": "The generated solution"
            }
        }
        
        self._brainstorming_decision_graph:BrainstormingGraph = self.create_node(
            BrainstormingGraph,
            name=f"{self.name}_brainstorming_decision_graph",
            critics_args=critics_args,
            solver_args=solver_args,
            critic_keys={f"advice_{i}": "The advice of you." for i in range(len(critics_args))},
            broadcast_label="broadcast",
            pull_keys=self._pull_keys,
            push_keys=self._push_keys
        )

        # Wire wrapper graph entry/exit to the inner brainstorming graph.
        # Without these edges, this wrapper would always output an empty dict.
        self.edge_from_entry(receiver=self._brainstorming_decision_graph, keys=self.input_keys)
        self.edge_to_exit(sender=self._brainstorming_decision_graph, keys=self.output_keys)
        super().build()
