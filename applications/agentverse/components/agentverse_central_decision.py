from masfactory import Graph, Agent, Model, Memory, Node
from masfactory.adapters.memory import HistoryMemory
from masfactory.utils.hook import masf_hook


class AgentverseCentralDecisionGraph(Graph):
    """Centralized decision graph: one critic then one solver.

    The critic runs first and its output is forwarded to the solver via the
    `analysis` input field. By default, both agents share a HistoryMemory.
    """
    
    def __init__(
        self,
        name: str,
        solver_role_name: str,
        solver_instructions: str | list[str],
        critic_role_name: str,
        critic_instructions: str | list[str],
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
        self._critic_role_name = critic_role_name
        self._critic_instructions = critic_instructions
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
        
        # Agents are created in build().
        self._solver = None
        self._critic = None
    
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
        
        # Build critic agent args.
        critic_instructions = self._critic_instructions
        if isinstance(critic_instructions, list):
            critic_instructions = list(critic_instructions)
            critic_instructions.append(
                "When analyzing the task, consider all involved agent roles. "
                "Provide a comprehensive analysis to help the solver make an informed decision."
            )
        else:
            critic_instructions = (
                f"{critic_instructions}\n\n"
                "When analyzing the task, consider all involved agent roles. "
                "Provide a comprehensive analysis to help the solver make an informed decision."
            )
        
        self._critic = self.create_node(
            Agent,
            name=f"{self.name}_critic",
            role_name=self._critic_role_name,
            instructions=critic_instructions,
            memories=self._critic_memories,
            model=self._model,
            pull_keys={},
            push_keys={}
        )
        
        # Build solver agent args.
        solver_instructions = self._solver_instructions
        if isinstance(solver_instructions, list):
            solver_instructions = list(solver_instructions)
            solver_instructions.append(
                "Based on the critic's analysis, generate the final solution. "
                "Consider all key points raised in the analysis."
            )
        else:
            solver_instructions = (
                f"{solver_instructions}\n\n"
                "Based on the critic's analysis, generate the final solution. "
                "Consider all key points raised in the analysis."
            )
        
        self._solver = self.create_node(
            Agent,
            name=f"{self.name}_solver",
            role_name=self._solver_role_name,
            instructions=solver_instructions,
            memories=self._solver_memories,
            model=self._model,
            pull_keys={},
            push_keys={}
        )
        
        self.edge_from_entry(
            receiver=self._critic,
            keys={}
        )
        
        self.create_edge(
            sender=self._critic,
            receiver=self._solver,
            keys={"analysis": "message"}
        )
        
        self.edge_to_exit(
            sender=self._solver,
            keys={"solution": "message"}
        )
        
        super().build()
