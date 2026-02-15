from masfactory import Graph, Agent, Model, Memory, Node
from masfactory import HistoryMemory
from masfactory import HorizontalGraph
from masfactory.utils.hook import masf_hook


class AgentverseHorizontalDecisionGraph(Graph):
    """Horizontal decision graph.

    Runs critics sequentially and then a solver agent to produce the final solution.
    """
    
    def __init__(
        self,
        name: str,
        solver_role_name: str,
        solver_instructions: str | list[str],
        critic_configs: list[dict],
        model: Model,
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
        
        # Shared chat history across agents.
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
        
        # Agent args are prepared in build().
        self._solver_args = None
        self._critics_args = []
    
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
                "solution": "Final solution"
            }
        
        self._solver_args = {
            "cls":Agent,
            "name":f"{self.name}_solver",
            "role_name":self._solver_role_name,
            "instructions":self._solver_instructions,
            "memories":self._solver_memories,
            "model":self._model,
            "pull_keys":self._pull_keys,
            "push_keys":self._push_keys
        }
        for i, critic_config in enumerate(self._critic_configs):
            self._critics_args.append(
                {
                    "cls":Agent,
                    "name": f"{self.name}_critic_{i}",
                    "role_name": critic_config.get("role_name", f"Critic {i+1}"),
                    "instructions": critic_config.get("instructions", "Provide critical feedback."),
                    "memories": self._critic_memories,
                    "model": self._model,
                    "pull_keys":{},
                    "push_keys":{}
                }
            )

        self._horizontal_graph = self.create_node(
            HorizontalGraph,
            name=f"{self.name}_horizontal_graph",
            node_args_list=self._critics_args + [self._solver_args],
            edge_keys_list=[{}] * len(self._critics_args) + [{"solution": "message"}],
        )   
        self.edge_from_entry(
            receiver=self._horizontal_graph,
            keys={}
        )
        self.edge_to_exit(
            sender=self._horizontal_graph,
            keys={"solution": "message"}
        )
        super().build()
