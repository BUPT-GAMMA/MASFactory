from masfactory import Graph, Agent, Model, Memory, CustomNode, Loop, LogicSwitch, Node
from masfactory.adapters.memory import HistoryMemory
from masfactory import VerticalDecisionGraph
from masfactory.utils.hook import masf_hook


class AgentverseConcurrentDecisionGraph(Graph):
    """Decision graph with an inner refinement loop over critic feedback.

    This wrapper builds a `VerticalDecisionGraph` where critics feed an
    aggregator, and the aggregator output is used by a solver. The inner loop
    stops when the terminate condition is met or when `max_inner_turns` is hit.
    """
    
    def __init__(
        self,
        name: str,
        solver_role_name: str,
        solver_instructions: str | list[str],
        critic_configs: list[dict],
        model: Model,
        max_inner_turns: int = 3,
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
        self._max_inner_turns = max_inner_turns
        
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
        
        def check_convergence(messages: dict, attributes: dict) -> bool:
            """Return True when no valid critic feedback is present."""
            return not bool(attributes.get("has_valid_feedback", False))

        # Build critic agents for the inner loop.
        critics_args = []
        for i, critic_config in enumerate(self._critic_configs):
            critic_args = {
                "cls":Agent,
                "name":f"{self.name}_critic_{i}",
                "role_name":critic_config.get("role_name", f"critic_{i+1}"),
                "instructions":critic_config.get("instructions", "provide critical feedback"),
                "memories":self._critic_memories,
                "model":self._model,
                "pull_keys":self._pull_keys,
                "push_keys":self._push_keys
            }
            critics_args.append(critic_args)
        
        def aggregate_and_filter(messages: dict, attributes: dict) -> dict:
            """Aggregate critic feedback into a single `advices` list."""
            return_messages = {"advices": []}
            for i in range(len(critics_args)):
                advice = messages.get(f"advice_{i}")
                if advice is None:
                    continue
                advice_text = str(advice).strip()
                if advice_text:
                    return_messages["advices"].append(advice_text)

            # Expose a convergence signal to the loop controller.
            attributes["has_valid_feedback"] = bool(return_messages["advices"])
            return return_messages
        
        aggregator_args = {
            "cls":CustomNode,
            "name":f"{self.name}_feedback_aggregator",
            "forward":aggregate_and_filter,
            "pull_keys":{},
            "push_keys":{
                "has_valid_feedback": "Whether any non-empty critic advice is present.",
            },
        }

        solver_args = {
            "cls": Agent,
            "name": f"{self.name}_solver",
            "role_name":self._solver_role_name,
            "instructions":self._solver_instructions,
            "memories":self._solver_memories,
            "model":self._model,
            "pull_keys":self._pull_keys,
            "push_keys":self._push_keys
        }
        vertical_decision_graph = self.create_node(
            VerticalDecisionGraph,
            name=f"{self.name}_vertical_decision_graph",
            critics_args=critics_args,
            aggregator_args=aggregator_args,
            solver_args=solver_args,
            critics_output_keys_list=[{f"advice_{i}": "the advice you put forward."} for i in range(len(critics_args))],
            solver_input_keys={"advices": "no advices yet."},
            terminate_condition_function=check_convergence,
            max_inner_turns=self._max_inner_turns,
            pull_keys=self._pull_keys,
            push_keys=self._push_keys
        )
        
        self.edge_from_entry(
            receiver=vertical_decision_graph,
            keys={}
        )
        self.edge_to_exit(
            sender=vertical_decision_graph,
            keys={"solution": "message"}
        )
        super().build()
