"""Task-solving pipeline graph.

Implements an AgentVerse-style 4-stage loop:
role assignment -> decision making -> (optional) execution -> evaluation.

Supported `executor_type` values:
- "code-test": write the solution to `tmp/main.py`, generate tests via an executor agent, then run locally.
- "bigcodebench-test": run dataset-provided unit tests locally (no executor agent).
- "coverage-test": compute concept coverage locally (no executor agent).
- "none": skip execution and evaluate the solution directly (brainstorming/pythoncalculator).
"""

import os
import re
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, Optional, Literal
from masfactory import Graph, Loop, Agent, Model, Node
from masfactory.components.custom_node import CustomNode
from masfactory.utils.hook import masf_hook
from .handlers import process_evaluation, role_extractor, parse_role_descriptions

# Supported executor types.
ExecutorType = Literal["code-test", "bigcodebench-test", "coverage-test", "none"]


def _write_text_with_retry(path: Path, text: str, *, attempts: int = 6, base_delay_s: float = 0.02) -> None:
    last: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return
        except OSError as e:
            last = e
            if getattr(e, "errno", None) not in {23, 24}:  # ENFILE=23, EMFILE=24
                raise
            time.sleep(base_delay_s * (2**i))
    if last is not None:
        raise last


@lru_cache(maxsize=1)
def _get_bigcodebench_untrusted_check():
    """Lazy-load the local BigCodeBench evaluator.

    We vendor a minimal `untrusted_check` implementation under
    `applications/agentverse/components/tasksolving/utils/` to avoid depending
    on `original_dataset/bigcodebench` at runtime.
    """

    from applications.agentverse.components.tasksolving.utils.bigcodebench_eval import untrusted_check

    return untrusted_check


class TaskSolvingPipelineGraph(Loop):
    """AgentVerse-style task-solving loop.

    Runs role assignment -> decision making -> optional execution -> evaluation,
    iterating up to `max_turn` until `attributes["success"]` becomes True.

    Args:
        name: Graph name.
        decision_graph_args: Arguments for creating the decision graph node.
        role_assigner_config: Config for the role assigner agent.
        evaluator_config: Config for the evaluator agent.
        executor_config: Config for the executor agent (when used).
        model: LLM model instance.
        max_turn: Maximum number of iterations.
        cnt_agents: Number of agents used by decision graphs (solver + critics).
        executor_type: Execution mode selector.
        success_threshold: Threshold used to compute `success`.
        pull_keys: MASFactory Node pull rule.
        push_keys: MASFactory Node push rule.
        initial_messages: Optional initial controller messages.
    """
    
    def __init__(
        self,
        name: str,
        decision_graph_args: dict[str, Any],
        role_assigner_config: dict[str, Any],
        evaluator_config: dict[str, Any],
        executor_config: Optional[dict[str, Any]],
        model: Model,
        max_turn: int = 10,
        cnt_agents: int = 3,
        executor_type: ExecutorType = "code-test",
        success_threshold: int = 1,  # 1 for boolean success; >1 for numeric thresholds.
        pull_keys: dict[str, Any] = None,
        push_keys: dict[str, Any] = None,
        initial_messages: dict[str, Any] | None = None,
    ):
        # Initialize loop attributes so child nodes can push outputs into the shared context.
        attributes = {
                "task_description": "",
                "advice": "",
                "previous_plan": "",
                "solution": "",
                "result": "",
                "score": 0,
                "message": "",
                "success": False,
                "cnt_critic_agents": cnt_agents,
                "success_threshold": success_threshold,
            }
        initial_messages = {
            "task_description": "",
            "previous_plan": "No solution yet.",
            "solution": "no solution yet.",
            "result": "",
            "score": 0,
            "advice": "No advice yet.",
            "message": "",
            "criticisms": "no criticisms yet.",
            "success": False,
        }
        super().__init__(
            name=name,
            max_iterations=max_turn,
            attributes=attributes,
            initial_messages=initial_messages,
            pull_keys=pull_keys,
            push_keys=push_keys,
            terminate_condition_function=lambda messages, attributes: attributes.get("success", False)
        )
        
        self._decision_graph_args = decision_graph_args
        self._role_assigner_config = role_assigner_config
        self._evaluator_config = evaluator_config
        self._executor_config = executor_config
        self._model = model
        self._max_turn = max_turn
        self._cnt_agents = cnt_agents
        self._executor_type = executor_type   
        
        # Node references (populated in build()).
        self._role_assigner = None
        self._evaluator = None
        self._solution_writer = None  # Writes solution to tmp/main.py for local executors.
        self._executor_agent = None
        self._executor_runner = None
        self._executor = None
            
    @masf_hook(Node.Hook.BUILD)
    def build(self):
        if self._is_built:
            return
        self._role_assigner = self.create_node(
            Agent,
            name=f"{self.name}_role_assigner",
            role_name=self._role_assigner_config.get("role_name", "Role Assigner"),
            instructions=self._role_assigner_config.get("prepend_prompt_template"),
            prompt_template=self._role_assigner_config.get("append_prompt_template"),
            model=self._model,
            model_settings=self._role_assigner_config.get("model_settings"),
            formatters=self._role_assigner_config.get("formatters"),
            pull_keys=None,  # Inherit loop attributes (task_description, advice, etc.).
            push_keys={"roles": "A list of role descriptions for critic and solver agents."},
            hide_unused_fields=True
        )
        
        decision_node = self.create_node(**self._decision_graph_args)

        # Snapshot the latest solution for the outer controller.
        # Also provide a reasonable default for `result` in non-executor pipelines.
        solution_snapshot = self.create_node(
            CustomNode,
            name=f"{self.name}_solution_snapshot",
            forward=lambda messages, attributes: {
                "solution": messages.get("solution", ""),
                "result": messages.get("solution", ""),
                "previous_plan": messages.get("solution", ""),
            },
            pull_keys=None,
            push_keys=None,
        )
        self.create_edge(
            sender=decision_node,
            receiver=solution_snapshot,
            keys={"solution": "The generated solution"},
        )
        self.edge_to_controller(
            sender=solution_snapshot,
            keys={
                "solution": "Latest solution",
                "result": "Latest result (defaults to solution if no executor)",
                "previous_plan": "Latest solution snapshot for next round",
            },
        )

        # Only create executor-related nodes when needed.
        if self._executor_type == "code-test":
            # Write `solution` into tmp/main.py (compatible with legacy CodeTestExecutor behavior).
            self._solution_writer = self.create_node(
                CustomNode,
                name=f"{self.name}_solution_writer",
                pull_keys=None,
                push_keys=None,
            )

            # Execution is split into:
            # 1) executor_agent: LLM generates a JSON payload (file_path/code/command/etc.).
            # 2) executor_runner: writes the test file and runs it locally, returning `result`.
            self._executor_agent = self.create_node(
                Agent,
                name=f"{self.name}_executor_agent",
                role_name=self._executor_config.get("role_name", "Executor") if self._executor_config else "Executor",
                instructions=self._executor_config.get("prepend_prompt_template") if self._executor_config else "",
                prompt_template=self._executor_config.get("append_prompt_template") if self._executor_config else "",
                model=self._model,
                model_settings=(self._executor_config.get("model_settings") if self._executor_config else None),
                formatters=(self._executor_config.get("formatters") if self._executor_config else None),
                pull_keys=None,  # Inherit loop attributes.
                push_keys=None,
                hide_unused_fields=True,
            )

            self._executor_runner = self.create_node(
                CustomNode,
                name=f"{self.name}_executor_runner",
                pull_keys=None,
                push_keys=None,
            )

            self._executor = self._executor_runner

            # Provide the shared loop context to the executor LLM (solution arrives from solution_writer).
            self.edge_from_controller(
                receiver=self._executor_agent,
                keys={
                    "task_description": "The task to solve",
                    "previous_plan": "Previous plan/solution attempt",
                    "advice": "Advice from evaluator",
                },
            )
        elif self._executor_type == "bigcodebench-test":
            # Run dataset-provided tests locally (no executor agent).
            self._solution_writer = self.create_node(
                CustomNode,
                name=f"{self.name}_solution_writer",
                pull_keys=None,
                push_keys=None,
            )
            self._executor_runner = self.create_node(
                CustomNode,
                name=f"{self.name}_executor_runner",
                pull_keys=None,
                push_keys=None,
            )
            self._executor = self._executor_runner
        elif self._executor_type == "coverage-test":
            # Compute concept coverage locally (no executor agent).
            from applications.agentverse.components.executors.coverage_test import CoverageTestExecutor

            executor_instance = None
            if isinstance(self._executor_config, dict):
                executor_instance = self._executor_config.get("executor_instance")
            if executor_instance is None:
                executor_instance = CoverageTestExecutor()

            self._executor_runner = self.create_node(
                CustomNode,
                name=f"{self.name}_coverage_test_executor",
                pull_keys=None,
                push_keys=None,
            )
            self._executor = self._executor_runner

            def _coverage_executor_forward(messages: dict, attributes: dict) -> dict:
                # IMPORTANT: `task_description` is a message input (from Controller), not an attribute.
                # If we mistakenly read from attributes here, it may stay empty and yield a bogus 100% coverage.
                task_description = messages.get("task_description", attributes.get("task_description", ""))
                solution = messages.get("solution", "")
                result_text = executor_instance.execute(task_description, str(solution))
                # Keep a copy on attributes for downstream nodes/logs.
                attributes["task_description"] = task_description
                attributes["result"] = result_text
                return {"result": result_text}

            self._executor_runner.set_forward(_coverage_executor_forward)

        if self._executor_type == "bigcodebench-test":
            # Deterministic evaluator: parse EXIT_CODE from executor output (no LLM call).
            self._evaluator = self.create_node(
                CustomNode,
                name=f"{self.name}_evaluator",
                pull_keys=None,
                push_keys=None,
            )

            def _local_bigcodebench_evaluator_forward(messages: dict, attributes: dict) -> dict:
                raw = messages.get("result")
                if raw is None:
                    raw = attributes.get("result", "")
                result_text = str(raw or "")

                exit_code = None
                m = re.search(r"(?m)^EXIT_CODE:\\s*(-?\\d+)\\s*$", result_text)
                if m:
                    try:
                        exit_code = int(m.group(1))
                    except ValueError:
                        exit_code = None
                passed = exit_code == 0
                advice = "" if passed else result_text
                return {"score": int(passed), "advice": advice}

            self._evaluator.set_forward(_local_bigcodebench_evaluator_forward)
        elif self._executor_type == "coverage-test":
            # Deterministic evaluator: parse Coverage/Missing Tokens from executor output (no LLM call).
            self._evaluator = self.create_node(
                CustomNode,
                name=f"{self.name}_evaluator",
                pull_keys=None,
                push_keys=None,
            )

            def _local_coverage_evaluator_forward(messages: dict, attributes: dict) -> dict:
                raw = messages.get("result")
                if raw is None:
                    raw = attributes.get("result", "")
                result_text = str(raw or "")

                cov = None
                m = re.search(r"(?im)^Coverage\\s*:\\s*([0-9.]+)\\s*%", result_text)
                if m:
                    try:
                        cov = float(m.group(1)) / 100.0
                    except ValueError:
                        cov = None

                passed = bool(cov is not None and cov >= 0.999999)
                advice = "" if passed else result_text
                return {"score": int(passed), "advice": advice}

            self._evaluator.set_forward(_local_coverage_evaluator_forward)
        else:
            self._evaluator = self.create_node(
                Agent,
                name=f"{self.name}_evaluator",
                role_name=self._evaluator_config.get("role_name", "Evaluator"),
                instructions=self._evaluator_config.get("prepend_prompt_template"),
                prompt_template=self._evaluator_config.get("append_prompt_template"),
                model=self._model,
                model_settings=self._evaluator_config.get("model_settings"),
                formatters=self._evaluator_config.get("formatters"),
                pull_keys=None,  # Inherit loop attributes.
                push_keys=None,
                hide_unused_fields=True,
            )
        
        self.edge_from_controller(
            receiver=self._role_assigner,
            keys={
                "task_description": "The task to solve",
                "advice": "Advice from evaluator",
                "previous_plan": "Previous plan/solution attempt",
            }
        )

        # Align with original AgentVerse semantics:
        # - role_assigner recruits `cnt_agents` experts for the whole group (solver + critics)
        # - the first role is assigned to the solver, the rest to critics
        role_dispatcher = self.create_node(
            CustomNode,
            name=f"{self.name}_role_dispatcher",
            pull_keys=None,
            push_keys={
                "roles": "All recruited role descriptions (as text)",
                "role_description": "Solver role description",
            },
        )

        def _role_dispatcher_forward(messages: dict, attributes: dict) -> dict:
            roles_list = parse_role_descriptions(messages.get("roles", []))

            solver_role = roles_list[0].strip().strip(".") if roles_list else "Solver"
            roles_text = "\n".join([r.strip().strip(".") for r in roles_list])

            return {
                "role_description": solver_role,
                "roles": roles_text,
            }

        role_dispatcher.set_forward(_role_dispatcher_forward)

        # Provide the shared loop context to the decision graph (and enforce ordering by also
        # waiting for role_assigner -> decision_node).
        self.edge_from_controller(
            receiver=decision_node,
            keys={
                "task_description": "The task to solve",
                "advice": "Advice from evaluator",
                "previous_plan": "Previous plan/solution attempt",
            },
        )

        # role_assigner -> role_dispatcher -> decision graph (provide solver role description)
        self.create_edge(
            sender=self._role_assigner,
            receiver=role_dispatcher,
            keys={"roles": "Role descriptions from role assigner"},
        )
        self.create_edge(
            sender=role_dispatcher,
            receiver=decision_node,
            keys={"role_description": "Solver role description"},
        )

        # Wire stage edges based on executor_type.
        if self._executor_type == "code-test":
            # code-test: write solution -> generate tests -> run tests.
            # Decision graph -> solution_writer (write solution to file)
            self.create_edge(
                sender=decision_node,
                receiver=self._solution_writer,
                keys={"solution": "The generated code solution"}
            )

            # solution_writer -> executor_agent (provide solution)
            self.create_edge(
                sender=self._solution_writer,
                receiver=self._executor_agent,
                keys={"solution": "message"}
            )

            # executor_agent -> executor_runner (provide test payload fields)
            self.create_edge(
                sender=self._executor_agent,
                receiver=self._executor_runner,
                keys={
                    "thought": "your thought",
                    "reasoning": "your reasoning on the testing cases",
                    "criticism": "constructive self-criticism",
                    "file_path": "the path to write your testing code",
                    "code": "the testing code with explanation in docstring",
                    "command": "the command to execute your testing code",
                },
            )

            # executor_runner -> evaluator (expose execution result only)
            self.create_edge(
                sender=self._executor_runner,
                receiver=self._evaluator,
                keys={"result": "The execution result or solution"}
            )
            # Also expose execution result to the outer controller for logging/output.
            self.edge_to_controller(
                sender=self._executor_runner,
                keys={"result": "The execution result"},
            )
        elif self._executor_type == "bigcodebench-test":
            # bigcodebench-test: write solution -> run BigCodeBench tests locally.
            self.create_edge(
                sender=decision_node,
                receiver=self._solution_writer,
                keys={"solution": "The generated code solution"},
            )
            # Trigger executor runner after solution is written.
            self.create_edge(
                sender=self._solution_writer,
                receiver=self._executor_runner,
                keys={"solution": "message"},
            )
            self.create_edge(
                sender=self._executor_runner,
                receiver=self._evaluator,
                keys={"result": "The execution result"},
            )
            self.edge_to_controller(
                sender=self._executor_runner,
                keys={"result": "The execution result"},
            )
        elif self._executor_type == "coverage-test":
            # coverage-test: decision graph -> coverage executor -> evaluator.
            # Coverage executor needs the task context from controller (solution arrives from decision graph).
            self.edge_from_controller(
                receiver=self._executor_runner,
                keys={
                    "task_description": "The task to solve",
                },
            )
            self.create_edge(
                sender=decision_node,
                receiver=self._executor_runner,
                keys={"solution": "The generated solution"},
            )
            self.create_edge(
                sender=decision_node,
                receiver=self._evaluator,
                keys={"solution": "The generated solution"},
            )
            self.create_edge(
                sender=self._executor_runner,
                receiver=self._evaluator,
                keys={"result": "The coverage test result"},
            )
            self.edge_to_controller(
                sender=self._executor_runner,
                keys={"result": "The execution result"},
            )
        else:
            # none: skip execution and pass the solution to the evaluator.
            self.create_edge(
                sender=decision_node,
                receiver=self._evaluator,
                keys={"solution": "The generated solution"}
            )
        
        
        # Post-process evaluation output to provide stable outer-loop fields:
        # - `message`: compatibility alias of `advice`
        # - `success`: computed deterministically from score + threshold
        evaluation_post = self.create_node(
            CustomNode,
            name=f"{self.name}_evaluation_post",
            pull_keys=None,
            push_keys=None,
        )

        def _evaluation_post_forward(messages: dict, attributes: dict) -> dict:
            score = messages.get("score", 0)
            advice = messages.get("advice", "No advice")

            def _coerce_number(v):
                if isinstance(v, (int, float, bool)):
                    return int(v) if isinstance(v, bool) else v
                if isinstance(v, str):
                    try:
                        return int(v)
                    except ValueError:
                        try:
                            return float(v)
                        except ValueError:
                            return 0
                return 0

            success_threshold = _coerce_number(attributes.get("success_threshold", 1))
            if isinstance(score, (list, tuple)):
                norm_score = [_coerce_number(s) for s in score]
            else:
                norm_score = _coerce_number(score)

            if success_threshold <= 1:
                success = all(bool(s) for s in norm_score) if isinstance(norm_score, list) else bool(norm_score)
            else:
                success = (
                    all(s >= success_threshold for s in norm_score)
                    if isinstance(norm_score, list)
                    else norm_score >= success_threshold
                )

            return {
                "score": norm_score,
                "advice": advice,
                "message": advice,
                "success": success,
            }

        evaluation_post.set_forward(_evaluation_post_forward)

        self.create_edge(
            sender=self._evaluator,
            receiver=evaluation_post,
            keys={
                "score": "The score of the solution",
                "advice": "The advice of the solution",
            },
        )

        # Evaluator also needs the task context from controller (solution/result arrive via other edges).
        self.edge_from_controller(
            receiver=self._evaluator,
            keys={
                "task_description": "The task to solve",
            },
        )

        self.edge_to_controller(
            sender=evaluation_post,
            keys={
                "score": "The score of the solution",
                "advice": "The advice of the solution",
                "message": "Compatibility alias of advice",
                "success": "Whether the task is solved",
            },
        )

        # Only set solution_writer forward for file-based executor modes.
        if self._executor_type in {"code-test", "bigcodebench-test"}:
            # Write the latest solution into tmp/main.py.
            def _solution_writer_forward(input: dict, attributes: dict) -> dict:
                solution = input.get("solution", "")
                # Extract code blocks if the solution is wrapped in Markdown fences.
                code_blocks = re.findall(r"```python\\n(.*?)```", str(solution), re.DOTALL)
                if code_blocks:
                    code_to_write = code_blocks[-1].strip()
                else:
                    code_blocks = re.findall(r"```\\n(.*?)```", str(solution), re.DOTALL)
                    if code_blocks:
                        code_to_write = code_blocks[-1].strip()
                    else:
                        code_to_write = str(solution).strip()

                try:
                    workdir = attributes.get("workdir")
                    base_dir = Path(str(workdir)).expanduser() if workdir else Path.cwd()
                    base_dir = base_dir.resolve()
                    tmp_dir = base_dir / "tmp"
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    _write_text_with_retry(tmp_dir / "main.py", code_to_write)
                except Exception as e:
                    print(f"Warning: failed to write solution to tmp/main.py: {e}")

                # Pass-through for downstream nodes.
                attributes["solution"] = solution
                return {"solution": solution}

            self._solution_writer.set_forward(_solution_writer_forward)

        # Only set the local executor runner forward in code-test mode.
        if self._executor_type == "code-test":
            # Write the generated test file and run it locally.
            def _executor_runner_forward(input: dict, attributes: dict) -> dict:
                file_path = input.get("file_path")
                code = input.get("code")
                command = input.get("command")

                result_text = ""

                try:
                    workdir = attributes.get("workdir")
                    base_dir = Path(str(workdir)).expanduser() if workdir else Path.cwd()
                    base_dir = base_dir.resolve()

                    # Normalize and validate file_path to avoid writing outside `tmp/`.
                    if not file_path:
                        file_path = "tmp/test_main.py"
                    if not isinstance(file_path, str):
                        file_path = str(file_path)

                    if os.path.isabs(file_path):
                        raise ValueError("Absolute file_path is not allowed")
                    if ".." in file_path.replace("\\", "/").split("/"):
                        raise ValueError("Parent directory traversal in file_path is not allowed")
                    if not file_path.replace("\\", "/").startswith("tmp/"):
                        raise ValueError("file_path must be under tmp/")
                    if not file_path.endswith(".py"):
                        raise ValueError("file_path must be a .py file")

                    # Write test file.
                    test_path = (base_dir / Path(file_path)).resolve()
                    if base_dir not in test_path.parents and test_path != base_dir:
                        raise ValueError("Resolved file_path escapes workdir")
                    test_path.parent.mkdir(parents=True, exist_ok=True)
                    if code:
                        code_text = str(code)
                        # Make executor-generated tests runnable under our execution model
                        # (`python tmp/test_main.py` from workdir). Many LLMs incorrectly
                        # write `from tmp.main import ...`, but `tmp` is not a package in this setup.
                        code_text = re.sub(
                            r"(?m)^from\\s+tmp\\.main\\s+import\\s+",
                            "from main import ",
                            code_text,
                        )
                        code_text = re.sub(r"(?m)^import\\s+tmp\\.main\\b", "import main", code_text)
                        code_text = re.sub(r"(?m)^from\\s+tmp\\s+import\\s+main\\b", "import main", code_text)
                        _write_text_with_retry(test_path, code_text)

                    # Execute tests safely: ignore arbitrary shell commands from the model.
                    # We always run the generated test file with the current Python interpreter.
                    # This prevents command injection and keeps behavior deterministic.
                    try:
                        proc = subprocess.run(
                            [sys.executable, str(test_path)],
                            capture_output=True,
                            text=True,
                            timeout=10,
                            cwd=str(base_dir),
                        )
                        result_text = f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                    except subprocess.TimeoutExpired as e:
                        timeout_val = getattr(e, "timeout", 10)
                        result_text = f"Execution timeout ({timeout_val}s)"
                except Exception as e:
                    result_text = f"Execution failed: {e}"

                attributes["result"] = result_text
                return {"result": result_text}

            self._executor_runner.set_forward(_executor_runner_forward)
        elif self._executor_type == "bigcodebench-test":
            # bigcodebench-test: run dataset-provided unit tests (no executor agent).
            def _executor_runner_forward(input: dict, attributes: dict) -> dict:
                result_text = ""
                try:
                    workdir = attributes.get("workdir")
                    base_dir = Path(str(workdir)).expanduser() if workdir else Path.cwd()
                    base_dir = base_dir.resolve()
                    tmp_dir = base_dir / "tmp"
                    tmp_dir.mkdir(parents=True, exist_ok=True)

                    test_code = attributes.get("test_code") or ""
                    entry_point = str(attributes.get("entry_point") or "task_func").strip() or "task_func"

                    try:
                        code_text = (tmp_dir / "main.py").read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        code_text = ""

                    # Match BigCodeBench official runner semantics:
                    # execute `code + test_code` in a single module namespace (so tests can access globals).
                    untrusted_check = _get_bigcodebench_untrusted_check()
                    stat, details = untrusted_check(
                        code_text,
                        str(test_code).strip(),
                        entry_point,
                        max_as_limit=30 * 1024,
                        max_data_limit=30 * 1024,
                        max_stack_limit=10,
                        min_time_limit=1,
                        gt_time_limit=20,
                    )
                    exit_code = 0 if stat == "pass" else (-1 if stat == "timeout" else 1)

                    details_text = ""
                    if isinstance(details, dict) and details:
                        parts: list[str] = []
                        for name, trace in list(details.items())[:12]:
                            trace_str = str(trace)
                            if len(trace_str) > 4000:
                                trace_str = trace_str[:4000] + "\\n...[truncated]"
                            parts.append(f"[{name}]\\n{trace_str}".rstrip())
                        details_text = "\\n\\n".join(parts)

                    if details_text:
                        result_text = f"EXIT_CODE: {exit_code}\\nSTATUS: {stat}\\nFAILURES:\\n{details_text}"
                    else:
                        result_text = f"EXIT_CODE: {exit_code}\\nSTATUS: {stat}"
                except Exception as e:
                    result_text = f"EXIT_CODE: -1\\nExecution failed: {e}"

                attributes["result"] = result_text
                return {"result": result_text}

            self._executor_runner.set_forward(_executor_runner_forward)

        super().build()

        for i in range(len(decision_node.critics)):
            # Roles[0] is reserved for the solver; critics start from Roles[1].
            decision_node.critics[i].hooks.register(Node.Hook.FORWARD.BEFORE, role_extractor(i + 1))
        self._evaluator.hooks.register(Node.Hook.FORWARD.AFTER, process_evaluation)

    def get_evaluator(self) -> Agent:
        return self._evaluator
    
    def get_executor(self) -> Optional[Agent]:
        return self._executor
