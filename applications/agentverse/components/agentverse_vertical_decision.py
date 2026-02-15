from masfactory import Graph, Agent, Model, Memory, CustomNode, Node
from masfactory import HistoryMemory
from masfactory import VerticalDecisionGraph
from masfactory.utils.hook import masf_hook


class AgentverseVerticalDecisionGraph(Graph):
    """Vertical decision graph: critics -> aggregator -> solver.

    Critics each produce one `advice_{i}` field. The aggregator collects these
    into a single `advices` list which is then provided to the solver.

    If `filter_agreement` is enabled, the aggregator drops low-signal "agreement"
    feedback (e.g., "looks good", "I agree") and keeps non-empty advice.
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
        filter_agreement: bool = True,
        pull_keys: dict[str, str] | None = None,
        push_keys: dict[str, str] | None = None,
        attributes: dict[str, object] | None = None,
    ):
        super().__init__(name, pull_keys, push_keys, attributes)
        
        self._solver_role_name = solver_role_name
        self._solver_instructions = solver_instructions
        self._critic_configs = critic_configs
        self._model = model
        self._filter_agreement = filter_agreement
        
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
        
        # Node references are created in build().
        self._solver = None
        self._critics = []
        self._aggregator = None
    
    @property
    def shared_history(self) -> HistoryMemory:
        return self._shared_history
    
    @masf_hook(Node.Hook.BUILD)
    def build(self):
        # Set default pull/push keys if not provided.
        if self._pull_keys is None:
            self._pull_keys = {
                "task_description": "no task description given",
                "previous_plan": "no previous plan yet.",
                "advices": "no advices yet."
            }
        
        if self._push_keys is None:
            self._push_keys = {
                "solution": "The solution you put forward."
            }
        
        # Build critic agents.
        critics_args = []
        for i, critic_config in enumerate(self._critic_configs):
            critics_args.append(
                {
                    "cls":Agent,
                    "name":f"{self.name}_critic_{i}",
                    "role_name":critic_config.get("role_name", f"critic {i+1}"),
                    "instructions":critic_config.get("instructions", "provide critical feedback"),
                    "memories":self._critic_memories,
                    "model":self._model,
                    "pull_keys":self._pull_keys,
                    "push_keys":{"advice_{}".format(i): "the advice you put forward."}
                }
            )
        
        def aggregate_feedback(messages: dict, attributes: dict) -> dict:
            """Aggregate `advice_{i}` fields into a single `advices` list."""

            advices: list[str] = []
            for i in range(len(critics_args)):
                advice = messages.get(f"advice_{i}")
                if advice is None:
                    continue
                advice_text = str(advice).strip()
                if advice_text:
                    advices.append(advice_text)

            if self._filter_agreement:
                agreement_only = {
                    "agree",
                    "i agree",
                    "looks good",
                    "sounds good",
                    "no issues",
                    "no problem",
                    "no changes",
                    "ok",
                    "okay",
                }
                advices = [
                    a
                    for a in advices
                    if a.strip().lower() not in agreement_only
                ]

            # Dedupe while preserving order.
            seen: set[str] = set()
            deduped: list[str] = []
            for a in advices:
                key = a.strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                deduped.append(a)

            return {"advices": deduped}
        
        aggregator_args = {
            "cls":CustomNode,
            "name":f"{self.name}_aggregator",
            "forward":aggregate_feedback,
            "pull_keys":{},
            "push_keys":{"advices": "the advices you put forward."}
        }
        
        # Build solver agent args.
        solver_args = {
            "cls": Agent,
            "name": f"{self.name}_solver",
            "role_name": self._solver_role_name,
            "instructions": self._solver_instructions,
            "memories": self._solver_memories,
            "model": self._model,
            "pull_keys":self._pull_keys,
            "push_keys":{"solution":"Your solution for the task."}
        }

        vertical_decision_graph = self.create_node(
            VerticalDecisionGraph,
            name=f"{self.name}_vertical_decision_graph",
            solver_args=solver_args,
            critics_args=critics_args,
            critics_output_keys_list=[{f"advice_{i}": "the advice you put forward."} for i in range(len(critics_args))],
            solver_input_keys={"advices": "no advices yet."},
            aggregator_args=aggregator_args,
            pull_keys=self._pull_keys,
            push_keys=self._push_keys
        )
        self.edge_from_entry(
            receiver=vertical_decision_graph,
            keys={}
        )
        self.edge_to_exit(
            sender=vertical_decision_graph,
            keys=self.output_keys
        )
        
        super().build()
