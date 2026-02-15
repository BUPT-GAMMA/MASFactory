from typing import List, Dict, Any
import re
from masfactory import Graph, Agent, Loop, HistoryMemory, Model, Node
from masfactory.components.custom_node import CustomNode
from masfactory import VerticalSolverFirstDecisionGraph
from masfactory.core.message import TwinsFieldTextFormatter
from masfactory.utils.hook import masf_hook
from applications.agentverse.formatters import CodeTwinsFieldTextFormatter

class AgentverseVerticalSolverFirstDecisionGraph(Graph):
    """Solver-first refinement decision graph.

    Compared to the classic vertical pattern (critics first, single solver pass),
    this graph runs a prepend-solver first, then iterates critic feedback and
    solver refinement for up to `max_inner_turns`.
    Flow:
    1) Solver proposes an initial draft.
    2) Critics provide feedback.
    3) Solver refines the draft iteratively until convergence or max turns.
    """
    
    def __init__(
        self,
        name: str,
        solver_config: dict,
        critic_configs: List[Dict[str, Any]],
        model: Model,
        max_inner_turns: int = 3,
        shared_memory: bool = True,
        hide_unused_fields: bool = True,
        **kwargs
    ):
        super().__init__(name=name, **kwargs)
        self._solver_config = solver_config
        self._critic_configs = critic_configs
        self._model = model
        self._max_inner_turns = max_inner_turns
        self._shared_memory = shared_memory
        self._hide_unused_fields = hide_unused_fields
        
        self._vertical_solver_first_decision_graph = None
        
        # Create shared memory (optional).
        if self._shared_memory:
            # Share a single HistoryMemory instance across solver/critics.
            self._shared_history = HistoryMemory(top_k=8, memory_size=1000)
            self._solver_memory = [self._shared_history]
            self._critic_memories = [self._shared_history]
        else:
            self._solver_memory = None
            self._critic_memories = None
        
    @property
    def prepend_solver(self) -> Agent:
        assert self._vertical_solver_first_decision_graph is not None, "VerticalSolverFirstDecisionGraph not built"
        return self._vertical_solver_first_decision_graph.prepend_solver
    @property
    def critics(self) -> list[Agent]:
        assert self._vertical_solver_first_decision_graph is not None, "VerticalSolverFirstDecisionGraph not built"
        return self._vertical_solver_first_decision_graph.critics
    @property
    def solver(self) -> Agent:
        assert self._vertical_solver_first_decision_graph is not None, "VerticalSolverFirstDecisionGraph not built"
        return self._vertical_solver_first_decision_graph.solver

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        solver_role_description = self._solver_config.get("role_name") or "Solver"
        solver_formatters = self._solver_config.get("formatters")
        solver_model_settings = self._solver_config.get("model_settings")
        if solver_formatters is None:
            # Align with original AgentVerse: solver outputs free-form python code (often fenced),
            # so avoid adding extra formatting constraints that can conflict with code generation.
            solver_formatters = [CodeTwinsFieldTextFormatter()]
        prepend_solver_args = {
            "cls": Agent,
            "name": f"{self.name}_solver",
            "role_name": self._solver_config.get("role_name"),
            "instructions": self._solver_config.get("prepend_prompt_template"),
            "prompt_template": self._solver_config.get("append_prompt_template"),
            "memories": self._solver_memory,
            "model": self._model,
            "pull_keys":{
                "task_description": "no task description given",
                "previous_plan": "no previous plan yet.",
                "advice": "no advice yet.",
                "role_description": "no role description given",
                "criticisms": "no criticisms yet."
            },
            "push_keys":{"solution":"The solution you put forward."},
            "attributes":{
                "task_description": "no task description given",
                "previous_plan": "no previous plan yet.",
                "advice": "no advice yet.",
                "role_description": solver_role_description,
                "criticisms": "no criticisms yet."
            },
            # Keep default behavior unless a task opts-in to exposing extra fields
            # (e.g., `previous_plan`/`advice`) for alignment with original AgentVerse.
            "hide_unused_fields": self._hide_unused_fields,
        }
        if solver_model_settings is not None:
            prepend_solver_args["model_settings"] = solver_model_settings
        if solver_formatters is not None:
            prepend_solver_args["formatters"] = solver_formatters
        
        critics_args = []
        for i, critic_config in enumerate(self._critic_configs):
            critic_args = {
                "cls":Agent,
                "name":f"{self.name}_critic_{i}",
                "role_name":critic_config.get("role_name", f"Critic {i+1}"),
                "instructions":critic_config.get("prepend_prompt_template"),
                "prompt_template":critic_config.get("append_prompt_template"),
                "memories":self._critic_memories,
                "model":self._model,
                # Critics should return plain text ending with [Agree]/[Disagree] (original AgentVerse style).
                # Avoid paragraph-format constraints that can cause the model to emit key/value blobs or JSON-like dicts.
                "formatters": critic_config.get("formatters") or [TwinsFieldTextFormatter()],
                "pull_keys":{
                    "task_description": "The task to solve",
                    "previous_plan": "Previous solution snapshot",
                    "advice": "Advice from evaluator",
                    "roles": "Description of the critic's role",
                    "solution": "The latest solution to be reviewed by the critic"
                },
                "push_keys":{},
                "hide_unused_fields": self._hide_unused_fields,
            }
            critic_formatters = critic_config.get("formatters")
            if critic_formatters is not None:
                critic_args["formatters"] = critic_formatters
            critic_model_settings = critic_config.get("model_settings")
            if critic_model_settings is not None:
                critic_args["model_settings"] = critic_model_settings
            critics_args.append(critic_args)
        
        def _is_agree(text: str) -> bool:
            lowered = text.lower()
            if "[agree]" in lowered:
                return True
            first_line = text.strip().splitlines()[0] if text.strip() else ""
            return bool(
                re.match(r"^(action|decision)\s*:\s*agree\b", first_line, flags=re.I)
            )

        def _extract_criticism(text: str) -> str:
            cleaned = (
                text.replace("[Agree]", "")
                .replace("[Disagree]", "")
                .strip()
            )

            # Action-based format (AgentVerse "critic" parser style)
            match = re.search(r"Action\s*Input\s*:\s*(.+)", cleaned, flags=re.I | re.S)
            if match:
                return match.group(1).strip()

            # Decision/Response format (responsegen-critic-2 style)
            match = re.search(r"Response\s*:\s*(.+)", cleaned, flags=re.I | re.S)
            if match:
                return match.group(1).strip()

            lines = cleaned.splitlines()
            if lines and re.match(r"^(action|decision)\s*:\s*disagree\b", lines[0], flags=re.I):
                return "\n".join(lines[1:]).strip()

            return cleaned

        def aggregate_feedback(messages: dict, attributes: dict) -> dict:
            criticisms: list[str] = []
            raw_bundle = messages.get("criticism")
            items: list[str] = []
            if isinstance(raw_bundle, list):
                items = [str(x) for x in raw_bundle]
            elif raw_bundle is not None:
                items = [str(raw_bundle)]

            roles_raw = attributes.get("roles")
            roles_list: list[str] = []
            if isinstance(roles_raw, list):
                roles_list = [str(r).strip() for r in roles_raw if str(r).strip()]
            elif isinstance(roles_raw, str) and roles_raw.strip():
                roles_list = [line.strip() for line in roles_raw.splitlines() if line.strip()]

            for i, text in enumerate(items):
                if not text.strip():
                    continue
                if _is_agree(text):
                    continue
                extracted = _extract_criticism(text)
                if extracted:
                    # Align with original AgentVerse: solver sees each critic message with a sender name.
                    role_tag = None
                    if roles_list and (i + 1) < len(roles_list):
                        role_tag = roles_list[i + 1]
                    if not role_tag:
                        role_tag = f"Critic {i+1}"
                    criticisms.append(f"[{role_tag}] {extracted}")

            formatted = "\n".join(f"- {c}" for c in criticisms) if criticisms else ""
            attributes["criticisms_list"] = criticisms
            attributes["criticisms"] = formatted
            attributes["has_valid_feedback"] = len(criticisms) > 0
            return {"criticisms": formatted, "criticisms_list": criticisms}
        aggregator_args = {
            "cls":CustomNode,
            "name":f"{self.name}_aggregator",
            "forward":aggregate_feedback,
            "attributes":{"criticisms": "no criticisms yet.",
                "has_valid_feedback": False}
        }
        solver_refiner_args = {
            "cls":Agent,
            "name":f"{self.name}_solver_refiner",
            "role_name":self._solver_config.get("role_name"),
            "instructions":self._solver_config.get("prepend_prompt_template"),
            "prompt_template":self._solver_config.get("append_prompt_template"),
            "memories":self._solver_memory,
            "model":self._model,
            "pull_keys":{
                "task_description": "The task to solve",
                "previous_plan": "Previous plan or solution",
                "advice": "Advice or feedback",
                "role_description": "Description of the solver's role",
            },
            "push_keys":{"solution":"The solution you put forward."},
            "attributes":{"task_description": "The task to solve",
                "previous_plan": "Previous plan or solution",
                "advice": "Advice or feedback",
                "criticisms": "no criticisms yet.",
                "role_description": solver_role_description},
            "hide_unused_fields": self._hide_unused_fields,
        }
        if solver_model_settings is not None:
            solver_refiner_args["model_settings"] = solver_model_settings
        if solver_formatters is not None:
            solver_refiner_args["formatters"] = solver_formatters
        def check_convergence(messages: dict, attributes: dict) -> bool:
            # Keep the latest draft as `previous_plan` for subsequent refinement.
            if "solution" in messages:
                attributes["previous_plan"] = messages["solution"]

            # IMPORTANT: the underlying `Loop.Controller` checks the terminate condition
            # immediately on its first execution (before any critic round runs).
            # To match original AgentVerse behavior (always run at least one critic round),
            # never terminate on the very first controller step.
            if attributes.get("current_iteration", 0) <= 1:
                return False

            # Terminate when there is no (valid) critic feedback to address.
            return not bool(attributes.get("has_valid_feedback", True))

        def pre_solver_should_terminate(messages: dict, attributes: dict) -> bool:
            # Stop before running solver_refiner if there is no valid critic feedback.
            return not bool(attributes.get("has_valid_feedback", True))
        self._vertical_solver_first_decision_graph:VerticalSolverFirstDecisionGraph = self.create_node(
            VerticalSolverFirstDecisionGraph,
            name=f"{self.name}_vertical_solver_first_decision_graph",
            prepend_solver_args=prepend_solver_args,
            prepend_solver_output_keys={"solution":"The solution you put forward."},
            critics_args=critics_args,
            critics_output_keys_list=[{"criticism": "Your review of the solution. End with \"[Agree]\" if correct, otherwise end with \"[Disagree]\"."} for _ in range(len(critics_args))],
            solver_args=solver_refiner_args,
            solver_input_keys={"criticisms":"no criticisms yet."},
            aggregator_args=aggregator_args,
            max_inner_turns=self._max_inner_turns,
            # Ensure the iterative phase (critics + solver_refiner) receives the original context,
            # otherwise critics/solver_refiner may see an empty {task_description}.
            entry_to_vertical_decision_graph_keys={
                "task_description": "The task to solve",
                "advice": "Advice from evaluator",
                "role_description": "Solver role description",
            },
            # Forward the same context to solver_refiner (works with and without the pre-solver switch).
            controller_to_solver_keys={
                "task_description": "The task to solve",
                "advice": "Advice from evaluator",
                "role_description": "Solver role description",
            },
            terminate_condition_function=check_convergence,
            pre_solver_terminate_condition_function=pre_solver_should_terminate,
            initial_messages={
                "solution": "no solution yet.",
                "criticisms": "no criticisms yet."
            }
        )
        self.edge_from_entry(
            receiver=self._vertical_solver_first_decision_graph,
            keys=self.input_keys
        )
        self.edge_to_exit(
            sender=self._vertical_solver_first_decision_graph,
            keys=self.output_keys
        )
        super().build()
