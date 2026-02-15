from masfactory.components.graphs.loop import Loop
from masfactory.components.agents.agent import Agent
from masfactory.components.controls.logic_switch import LogicSwitch
from masfactory.components.custom_node import CustomNode
from masfactory.adapters.model import Model
from typing import Optional, Dict, Any
import logging
from .components import (
    EngineerAgent,
    CodeReviewAgent,
    init_task_state_forward,
    pick_task_forward,
    run_code_forward,
    update_task_state_forward,
_write_codebase_to_disk,
)

logger = logging.getLogger(__name__)


class DevLoop(Loop):
    """Development loop orchestrating task queues, coding, and execution feedback."""
    
    def __init__(
        self,
        name: str,
        model: Model,
        max_iterations: int = 1000,
        max_retries_per_task: int = 3,
        pull_keys: Optional[dict[str, str]] = None,
        push_keys: Optional[dict[str, str]] = None,
        attributes: Optional[dict[str, object]] = None,
    ):
        if attributes is None:
            attributes = {}

        def devloop_terminate_condition(input_msg: dict, attrs: dict) -> bool:
            """
            Return True when every task in the controller-managed queue has
            completed. The controller message cache provides authoritative queue
            length and index information.
            """


            queue_raw = input_msg.get("task_queue", [])
            idx_raw = input_msg.get("current_task_index", 0)
            

            if isinstance(queue_raw, list):
                queue = queue_raw
            elif isinstance(queue_raw, str):

                logger.debug(f"  → task_queue is string (not initialized), not terminating")
                return False
            else:
                queue = []
            

            if isinstance(idx_raw, list):

                idx = int(idx_raw[-1]) if len(idx_raw) > 0 else 0
            elif isinstance(idx_raw, (int, float)):
                idx = int(idx_raw)
            else:
                idx = 0
            

            logger.debug(f"\n[devloop_terminate_condition] Checking termination:")
            logger.debug(f"  → task_queue from input_msg: type={type(queue)}, len={len(queue) if isinstance(queue, list) else 'N/A'}")
            logger.debug(f"  → current_task_index from input_msg: {idx} (raw: {idx_raw})")
            

            if not queue or len(queue) == 0:
                logger.debug(f"  → task_queue is empty, not terminating (waiting for initialization)")
                return False
            
            should_terminate = idx >= len(queue)
            if should_terminate:
                logger.debug(f"✓ DevLoop terminating: completed {idx}/{len(queue)} tasks")
            return should_terminate
        
        super().__init__(
            name=name,
            max_iterations=max_iterations,
            terminate_condition_function=devloop_terminate_condition,
            pull_keys=pull_keys if pull_keys is not None else {
                "task_list": "Task list from Project Manager",
                "system_design": "System design from Architect",
                "project_path": "Project path (from root attributes)",
            },
            push_keys=push_keys if push_keys is not None else {
                "codebase": "Complete codebase with all implemented files",
            },
            attributes=attributes if attributes is not None else {},


            initial_messages={
                "codebase": {},
                "current_task_index": 0,
                "current_task": None,
                "current_task_retry_count": 0,
                "runtime_log": "",
                "error_message": "",
                "task_queue": [],

                "task_list": [],
                "system_design": {},
            },
        )
        
        self._model = model
        self._max_retries_per_task = max_retries_per_task
        

        self._build_graph()
    
    def _build_graph(self):
        """Construct the internal DevLoop graph with all agent nodes and flows."""
        
        def normalize_retry_count(value) -> int:
            """Ensure the retry counter is always coerced to an integer."""
            if isinstance(value, list):
                for item in reversed(value):
                    normalized = normalize_retry_count(item)
                    if normalized is not None:
                        return normalized
                return 0
            if isinstance(value, (int, float)):
                return int(value)
            if value in (None, "", False):
                return 0
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
        

        init_task_state = self.create_node(
            CustomNode,
            name=f"{self.name}_init_task_state",
            forward=init_task_state_forward,
            pull_keys={
                "task_list": "Task list from Project Manager",
                "system_design": "System design from Architect",
                "project_path": "Project path (from root attributes)",
            },
        )
        

        pick_task = self.create_node(
            CustomNode,
            name=f"{self.name}_pick_task",
            forward=pick_task_forward,
        )
        

        task_switch = self.create_node(
            LogicSwitch,
            name=f"{self.name}_task_switch"
        )
        

        engineer = self.create_node(
            EngineerAgent,
            name=f"{self.name}_engineer",
            model=self._model,
            pull_keys={
                "current_task": "Current task to implement",
                "system_design": "System design document",
                "codebase": "Current codebase",
            },
            push_keys={
                "code": "Implemented code",
                "file_name": "File name for the code",
                "implementation_status": "Status of implementation",
            },
        )
        
        def store_engineer_output_forward(input: dict, attributes: dict) -> dict:
            code = input.get("code")
            file_name = input.get("file_name")
            current_task = input.get("current_task") or attributes.get("current_task") or {}
            retry_count = normalize_retry_count(
                input.get("current_task_retry_count", attributes.get("current_task_retry_count", 0))
            )
            if code:
                attributes["latest_engineer_code"] = code
            if file_name:
                attributes["latest_engineer_file"] = file_name
            attributes["current_task"] = current_task
            attributes["current_task_retry_count"] = retry_count
            if not isinstance(current_task, dict):
                current_task = {"description": str(current_task)}
            return {
                "code": code,
                "file_name": file_name,
                "current_task": current_task,
                "current_task_retry_count": retry_count,
            }
        
        code_buffer = self.create_node(
            CustomNode,
            name=f"{self.name}_code_buffer",
            forward=store_engineer_output_forward,
        )
        self.edge_from_controller(
            receiver=code_buffer,
            keys={
                "current_task_retry_count": "current_task_retry_count",
                "current_task": "current_task",
            }
        )
        
        code_review = self.create_node(
            CodeReviewAgent,
            name=f"{self.name}_code_review",
            model=self._model,
            pull_keys={
                "code": "Code to review",
                "file_name": "Target file",
                "current_task": "Current task description",
                "system_design": "System design document",
                "codebase": "Current codebase",
            },
        )
        
        def code_ready_forward(input: dict, attributes: dict) -> dict:
            final_code = input.get("code") or attributes.get("latest_engineer_code", "")
            final_file = input.get("file_name") or attributes.get("latest_engineer_file")
            codebase = input.get("codebase", attributes.get("codebase", {}))
            return {
                "code": final_code,
                "file_name": final_file,
                "current_task": input.get("current_task", attributes.get("current_task")),
                "current_task_retry_count": normalize_retry_count(
                    input.get("current_task_retry_count", attributes.get("current_task_retry_count", 0))
                ),
                "codebase": codebase,
            }
        
        code_ready = self.create_node(
            CustomNode,
            name=f"{self.name}_code_ready",
            forward=code_ready_forward,
        )
        

        run_code = self.create_node(
            CustomNode,
            name=f"{self.name}_run_code",
            forward=run_code_forward,
            pull_keys={
                "code": "Implemented code",
                "file_name": "File name",
                "current_task": "Current task",
            },
        )
        

        update_task_state = self.create_node(
            CustomNode,
            name=f"{self.name}_update_task_state",
            forward=update_task_state_forward,
            pull_keys={
                "codebase": "Updated codebase",
                "current_task": "Current task",
                "project_path": "Project path (from root attributes)",
                "current_task_retry_count": "Current task retry count",
            },
        )
        

        

        self.edge_from_controller(
            receiver=init_task_state,
            keys={
                "task_list": "Task list from Project Manager",
                "system_design": "System design from Architect",
                "project_path": "Project path (from root attributes)",
            }
        )
        



        self.edge_to_controller(
            sender=init_task_state,
            keys={
                "task_queue": "Task queue",
                "current_task_index": "Current task index",
                "codebase": "Initial codebase (empty dict)",
                "current_task_retry_count": "Current task retry count",
            }
        )
        
        # PickTask -> TaskSwitch
        self.create_edge(
            sender=pick_task,
            receiver=task_switch,
            keys={
                "has_task": "Whether there are more tasks",
                "current_task": "Current task if available",
                "current_task_retry_count": "Current task retry count",
            }
        )
        
        # TaskSwitch -> Engineer (has_task == True)

        edge_task_to_engineer = self.create_edge(
            sender=task_switch,
            receiver=engineer,
            keys={
                "current_task": "Current task to implement",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        
        # TaskSwitch -> Loop.Exit (has_task == False)

        def prepare_exit_output_forward(input: dict, attributes: dict) -> dict:
            """Prepare the loop output payload before termination."""

            codebase = attributes.get("codebase", {})
            if not isinstance(codebase, dict):
                codebase = {}
            return {
                "codebase": codebase,
            }
        
        exit_preparer = self.create_node(
            CustomNode,
            name=f"{self.name}_exit_preparer",
            forward=prepare_exit_output_forward,
        )
        
        edge_task_to_exit = self.create_edge(
            sender=task_switch,
            receiver=exit_preparer,
            keys={}
        )
        
        # Exit Preparer -> Loop.TerminateNode

        self.edge_to_terminate_node(
            sender=exit_preparer,
            keys={
                "codebase": "Complete codebase",
            }
        )
        

        def has_task(message: dict, attrs: dict) -> bool:
            return bool(message.get("has_task", False))
        
        def no_task(message: dict, attrs: dict) -> bool:
            return not has_task(message, attrs)
        
        task_switch.condition_binding(has_task, edge_task_to_engineer)
        task_switch.condition_binding(no_task, edge_task_to_exit)
        

        self.create_edge(
            sender=engineer,
            receiver=code_buffer,
            keys={
                "code": "code",
                "file_name": "file_name",
            }
        )
        

        self.create_edge(
            sender=code_buffer,
            receiver=code_review,
            keys={
                "code": "code",
                "file_name": "file_name",
                "current_task": "current_task",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        

        self.create_edge(
            sender=code_buffer,
            receiver=run_code,
            keys={
                "code": "code",
                "file_name": "file_name",
                "current_task": "current_task",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        

        def merge_test_results_forward(input: dict, attributes: dict) -> dict:
            """
            Merge outputs from the code review and run-code branches. Success
            requires both branches to pass; otherwise, collect error details.
            """

            review_result = input.get("review_result", "")
            run_status = input.get("run_status", "")
            

            review_passed = str(review_result).lower() == "lgtm"
            run_passed = str(run_status).lower() in ["success", "skipped_gui", "skipped_cli"]
            
            logger.debug(f"\n[MergeTestResults]")
            logger.debug(f"  → Code Review: {review_result} ({'PASS' if review_passed else 'FAIL'})")
            logger.debug(f"  → Run Code: {run_status} ({'PASS' if run_passed else 'FAIL'})")
            
            all_passed = review_passed and run_passed
            

            error_messages = []
            if not review_passed:
                comments = input.get("review_comments", [])
                actions = input.get("actions", [])
                error_messages.append("[Code Review Failed]")
                if isinstance(comments, list):
                    error_messages.extend(f"  - {c}" for c in comments)
                if isinstance(actions, list) and actions != ["pass"]:
                    error_messages.extend(f"  Action: {a}" for a in actions)
            
            if not run_passed:
                run_error = input.get("error_message", "")
                runtime_log = input.get("runtime_log", "")
                error_messages.append("[Code Execution Failed]")
                if run_error:
                    error_messages.append(f"  Error: {run_error}")
                if runtime_log and runtime_log != run_error:
                    error_messages.append(f"  Log: {runtime_log}")
            
            combined_error = "\n".join(error_messages) if error_messages else ""
            
            return {
                "all_tests_passed": all_passed,
                "review_result": review_result,
                "run_status": run_status,
                "code": input.get("code", ""),
                "file_name": input.get("file_name", ""),
                "current_task": input.get("current_task", {}),
                "codebase": input.get("codebase", {}),
                "combined_error_message": combined_error,
                "runtime_log": combined_error,
                "current_task_retry_count": normalize_retry_count(
                    input.get("current_task_retry_count", attributes.get("current_task_retry_count", 0))
                ),
            }
        
        merge_results = self.create_node(
            CustomNode,
            name=f"{self.name}_merge_test_results",
            forward=merge_test_results_forward,
            pull_keys={
                "review_result": "Review result from CodeReviewAgent",
                "review_comments": "Review comments",
                "actions": "Review actions",
                "run_status": "Run status from RunCode",
                "runtime_log": "Runtime log from RunCode",
                "error_message": "Error message from RunCode",
                "code": "Code",
                "file_name": "File name",
                "current_task": "Current task",
                "codebase": "Current codebase",
            },
        )
        self.edge_from_controller(
            receiver=merge_results,
            keys={
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        
        # Code review -> Merge results
        self.create_edge(
            sender=code_review,
            receiver=merge_results,
            keys={
                "review_result": "review_result",
                "review_comments": "review_comments",
                "actions": "actions",
            }
        )
        
        # RunCode -> Merge results
        self.create_edge(
            sender=run_code,
            receiver=merge_results,
            keys={
                "run_status": "run_status",
                "runtime_log": "runtime_log",
                "error_message": "error_message",
                "codebase": "codebase",
            }
        )
        
        # Merge results -> Test result switch
        test_result_switch = self.create_node(
            LogicSwitch,
            name=f"{self.name}_test_result_switch"
        )
        
        self.create_edge(
            sender=merge_results,
            receiver=test_result_switch,
            keys={
                "all_tests_passed": "all_tests_passed",
                "code": "code",
                "file_name": "file_name",
                "current_task": "current_task",
                "codebase": "codebase",
                "combined_error_message": "combined_error_message",
                "runtime_log": "runtime_log",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        

        def check_retry_limit_forward(input: dict, attributes: dict) -> dict:
            """Determine whether the current task can retry again."""
            retry_count = normalize_retry_count(input.get("current_task_retry_count", 0))
            max_retries = attributes.get("max_retries_per_task", 3)
            
            logger.debug(f"\n[RetryCheck] Current retry count: {retry_count}/{max_retries}")
            
            can_retry = retry_count < max_retries
            
            if not can_retry:
                logger.debug(f"  → Max retries reached, skipping this task")
            
            return {
                "can_retry": can_retry,
                "retry_count": retry_count,
                "combined_error_message": input.get("combined_error_message", ""),
                "runtime_log": input.get("runtime_log", ""),
                "current_task": input.get("current_task", {}),
                "codebase": input.get("codebase", {}),
                "current_task_retry_count": retry_count,
            }
        
        retry_checker = self.create_node(
            CustomNode,
            name=f"{self.name}_retry_checker",
            forward=check_retry_limit_forward,
            attributes={
                "max_retries_per_task": self._max_retries_per_task,
            },
        )
        
        # Test failed -> Retry checker
        edge_test_fail_to_retry_check = self.create_edge(
            sender=test_result_switch,
            receiver=retry_checker,
            keys={
                "combined_error_message": "combined_error_message",
                "runtime_log": "runtime_log",
                "current_task": "current_task",
                "codebase": "codebase",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        

        retry_router = self.create_node(
            LogicSwitch,
            name=f"{self.name}_retry_router"
        )
        
        self.create_edge(
            sender=retry_checker,
            receiver=retry_router,
            keys={
                "can_retry": "can_retry",
                "retry_count": "retry_count",
                "combined_error_message": "combined_error_message",
                "runtime_log": "runtime_log",
                "current_task": "current_task",
                "codebase": "codebase",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        

        def increment_retry_forward(input: dict, attributes: dict) -> dict:
            """Increment the retry counter when another attempt is allowed."""
            retry_count = normalize_retry_count(input.get("current_task_retry_count", 0))
            new_count = retry_count + 1
            attributes["current_task_retry_count"] = new_count
            
            logger.debug(f"  → Incrementing retry count to {new_count}")
            
            return {
                "runtime_log": input.get("runtime_log", ""),
                "error_message": input.get("combined_error_message", ""),
                "current_task": input.get("current_task", {}),
                "codebase": input.get("codebase", {}),
                "current_task_retry_count": new_count,
            }
        
        increment_retry = self.create_node(
            CustomNode,
            name=f"{self.name}_increment_retry",
            forward=increment_retry_forward,
        )
        
        edge_can_retry = self.create_edge(
            sender=retry_router,
            receiver=increment_retry,
            keys={
                "retry_count": "retry_count",
                "runtime_log": "runtime_log",
                "combined_error_message": "combined_error_message",
                "current_task": "current_task",
                "codebase": "codebase",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        

        self.edge_to_controller(
            sender=increment_retry,
            keys={
                "runtime_log": "runtime_log",
                "error_message": "error_message",
                "current_task": "current_task",
                "codebase": "codebase",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        

        def skip_task_forward(input: dict, attributes: dict) -> dict:
            """Skip the current task after exhausting retries and reset counters."""
            attributes["current_task_retry_count"] = 0
            
            logger.debug(f"  → Skipping task due to max retries, moving to next task")
            
            codebase = input.get("codebase", {})
            project_path = attributes.get("project_path", "./projects/default")
            if codebase:
                written = _write_codebase_to_disk(codebase, project_path)
                if written:
                    logger.debug(f"  → Persisted {len(written)} files to {project_path} before skipping")
            

            return {
                "codebase": codebase,
                "current_task": input.get("current_task", {}),
                "current_task_retry_count": 0,
            }
        
        skip_task = self.create_node(
            CustomNode,
            name=f"{self.name}_skip_task",
            forward=skip_task_forward,
        )
        
        edge_cannot_retry = self.create_edge(
            sender=retry_router,
            receiver=skip_task,
            keys={
                "current_task": "current_task",
                "codebase": "codebase",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        

        self.create_edge(
            sender=skip_task,
            receiver=update_task_state,
            keys={
                "current_task": "current_task",
                "codebase": "codebase",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        

        def can_retry_condition(message: dict, attrs: dict) -> bool:
            return bool(message.get("can_retry", False))
        
        def cannot_retry_condition(message: dict, attrs: dict) -> bool:
            return not can_retry_condition(message, attrs)
        
        retry_router.condition_binding(can_retry_condition, edge_can_retry)
        retry_router.condition_binding(cannot_retry_condition, edge_cannot_retry)
        
        # Test passed -> Code ready -> Update task state
        edge_test_pass = self.create_edge(
            sender=test_result_switch,
            receiver=code_ready,
            keys={
                "code": "code",
                "file_name": "file_name",
                "current_task": "current_task",
                "codebase": "codebase",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        

        def reset_retry_and_update_forward(input: dict, attributes: dict) -> dict:
            """Reset retry counters after tests succeed and pass data downstream."""
            attributes["current_task_retry_count"] = 0
            return {
                **input,
                "current_task_retry_count": 0,
            }
        
        reset_retry = self.create_node(
            CustomNode,
            name=f"{self.name}_reset_retry",
            forward=reset_retry_and_update_forward,
        )
        
        self.create_edge(
            sender=code_ready,
            receiver=reset_retry,
            keys={
                "code": "code",
                "file_name": "file_name",
                "current_task": "current_task",
                "codebase": "codebase",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        
        self.create_edge(
            sender=reset_retry,
            receiver=update_task_state,
            keys={
                "code": "code",
                "file_name": "file_name",
                "current_task": "current_task",
                "codebase": "codebase",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        

        def all_tests_passed(message: dict, attrs: dict) -> bool:
            return bool(message.get("all_tests_passed", False))
        
        def some_tests_failed(message: dict, attrs: dict) -> bool:
            return not all_tests_passed(message, attrs)
        
        test_result_switch.condition_binding(all_tests_passed, edge_test_pass)
        test_result_switch.condition_binding(some_tests_failed, edge_test_fail_to_retry_check)
        

        self.edge_to_controller(
            sender=update_task_state,
            keys={
                "current_task_index": "Updated task index",
                "codebase": "Updated codebase",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        


        self.edge_from_controller(
            receiver=pick_task,
            keys={
                "task_queue": "Task queue (from controller)",
                "current_task_index": "Current task index (from controller)",
                "codebase": "Current codebase (from controller)",
                "current_task_retry_count": "current_task_retry_count",

            }
        )
        



        edge_controller_to_engineer = self.edge_from_controller(
            receiver=engineer,
            keys={
                "current_task": "Current task (from controller, includes error info)",
                "codebase": "Current codebase (from controller)",
                "runtime_log": "Runtime log with error information",
                "error_message": "Error message",
                "current_task_retry_count": "current_task_retry_count",
            }
        )
        




    
    def _forward(self, input: dict[str, object]) -> dict[str, object]:
        """
        Override the base Loop forward pass to merge root attributes (system
        design, project path) into the controller input and to guarantee the
        codebase is returned in the final output.
        """

        logger.debug(f"\n{'='*60}")
        logger.debug(f"[DevLoop._forward] Input keys: {list(input.keys())}")
        logger.debug(f"  → task_list from input: type={type(input.get('task_list'))}, value={input.get('task_list')}")
        logger.debug(f"  → attributes_store keys: {list(self._attributes_store.keys())}")
        logger.debug(f"  → system_design from attributes: type={type(self._attributes_store.get('system_design'))}, keys={list(self._attributes_store.get('system_design', {}).keys()) if isinstance(self._attributes_store.get('system_design'), dict) else 'N/A'}")
        logger.debug(f"{'='*60}\n")
        

        system_design = self._attributes_store.get("system_design", {})
        project_path = self._attributes_store.get("project_path", "./projects/default")
        

        self._attributes_store["max_retries_per_task"] = self._max_retries_per_task
        


        enhanced_input = {
            **input,
            "system_design": system_design,
            "project_path": project_path,
        }
        
        logger.debug(f"[DevLoop._forward] Enhanced input keys: {list(enhanced_input.keys())}")
        logger.debug(f"  → task_list: type={type(enhanced_input.get('task_list'))}, len={len(enhanced_input.get('task_list', []))}")
        logger.debug(f"  → system_design: type={type(enhanced_input.get('system_design'))}, keys={list(enhanced_input.get('system_design', {}).keys()) if isinstance(enhanced_input.get('system_design'), dict) else 'N/A'}")
        
        result = super()._forward(enhanced_input)
        


        if "codebase" not in result or result.get("codebase") is None:
            codebase = self._attributes_store.get("codebase", {})
            if not isinstance(codebase, dict):
                codebase = {}
            result["codebase"] = codebase
        


        return result
