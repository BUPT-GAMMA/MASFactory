"""Task execution component: handles task dependencies and execution.

This module provides the TaskExecutor class, which manages the execution of tasks
with dependency resolution, model selection, and inference coordination.
"""

import json
import copy
from typing import Dict, List, Optional
from pathlib import Path
from masfactory.components.custom_node import CustomNode

# Import adapters
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from adapters.huggingface_adapter import HuggingFaceAdapter
from adapters.local_adapter import LocalAdapter
from adapters.model_selector import ModelSelector


class TaskExecutor(CustomNode):
    """Task execution node: handles task dependencies and executes tasks.
    
    This node manages the execution of a list of tasks, resolving dependencies,
    selecting appropriate models, and coordinating inference across different
    model providers (local, HuggingFace, ChatGPT).
    """
    
    def __init__(
        self,
        name: str,
        model,
        models_map: Dict[str, List[Dict]],
        models_metadata: Dict[str, Dict],
        inference_mode: str = "hybrid",
        local_server: Optional[str] = None,
        huggingface_token: Optional[str] = None,
        proxy: Optional[str] = None,
        num_candidate_models: int = 5,
        max_description_length: int = 100,
        pull_keys: Optional[Dict[str, str]] = None,
        push_keys: Optional[Dict[str, str]] = None,
        **kwargs
    ):
        """Initialize task executor.
        
        Args:
            name: Node name.
            model: Model adapter (used for model selection).
            models_map: Model mapping organized by task type.
            models_metadata: Model metadata dictionary.
            inference_mode: Inference mode (local/huggingface/hybrid).
            local_server: Local model server address.
            huggingface_token: HuggingFace access token.
            proxy: Proxy address for requests.
            num_candidate_models: Number of candidate models to consider.
            max_description_length: Maximum description length for model selection.
        """
        super().__init__(
            name=name,
            forward=self._execute_tasks,
            pull_keys=pull_keys or {
                "tasks": "Parsed task list",
                "user_input": "User input"
            },
            push_keys=push_keys or {
                "task_results": "Task execution results",
                "tasks": "Task list (passed through)",
                "user_input": "User input (passed through)"
            },
            **kwargs
        )
        self._model = model
        self._models_map = models_map
        self._models_metadata = models_metadata
        self._inference_mode = inference_mode
        self._local_server = local_server
        self._huggingface_token = huggingface_token
        self._proxy = proxy
        self._num_candidate_models = num_candidate_models
        self._max_description_length = max_description_length
        
        # Initialize adapters
        self._hf_adapter = HuggingFaceAdapter(token=huggingface_token, proxy=proxy) if huggingface_token else None
        self._local_adapter = LocalAdapter(
            host=local_server.split("://")[1].split(":")[0] if local_server and "://" in local_server else "localhost",
            port=int(local_server.split(":")[-1]) if local_server and ":" in local_server else 8005
        ) if local_server else None
        self._model_selector = ModelSelector(
            huggingface_token=huggingface_token,
            local_server=local_server,
            proxy=proxy
        )
    
    def _execute_tasks(self, input_dict: dict[str, object]) -> dict[str, object]:
        """Execute task list.
        
        Args:
            input_dict: Input dictionary containing tasks and user_input.
        
        Returns:
            Output dictionary containing task_results.
        """
        tasks = input_dict.get("tasks", [])
        user_input = input_dict.get("user_input", "")
        
        if not tasks:
            return {"task_results": {}}
        
        # Unfold tasks (handle multiple GENERATED resources)
        tasks = self._unfold_tasks(tasks)
        # Fix dependencies
        tasks = self._fix_dependencies(tasks)
        
        # Execute tasks
        results = {}
        executed = set()
        remaining_tasks = tasks.copy()
        
        while remaining_tasks:
            # Find executable tasks (dependencies satisfied)
            ready_tasks = [
                task for task in remaining_tasks
                if self._can_execute(task, results, executed)
            ]
            
            if not ready_tasks:
                # No executable tasks, possible circular dependency
                # Log warning but continue to avoid infinite loop
                break
            
            # Execute ready tasks
            for task in ready_tasks:
                task_result = self._run_task(task, results, user_input)
                results[task["id"]] = task_result
                executed.add(task["id"])
                remaining_tasks.remove(task)
        
        return {
            "task_results": results,
            "tasks": tasks,  # Also return tasks for passing through
            "user_input": user_input  # Pass user_input to next node
        }
    
    def _unfold_tasks(self, tasks: List[Dict]) -> List[Dict]:
        """Unfold tasks: handle cases with multiple GENERATED resources."""
        unfolded = []
        for task in tasks:
            args = task.get("args", {})
            for key, value in args.items():
                if isinstance(value, str) and "<GENERATED>" in value:
                    items = value.split(",")
                    if len(items) > 1:
                        # Need to unfold
                        for item in items:
                            new_task = copy.deepcopy(task)
                            dep_id = int(item.split("-")[1])
                            new_task["dep"] = [dep_id]
                            new_task["args"][key] = item.strip()
                            unfolded.append(new_task)
                        break
            else:
                unfolded.append(task)
        return unfolded
    
    def _fix_dependencies(self, tasks: List[dict]) -> List[dict]:
        """Fix task dependencies."""
        for task in tasks:
            args = task.get("args", {})
            deps = []
            task_id = task.get("id", -1)
            
            for key, value in args.items():
                if isinstance(value, str) and "<GENERATED>" in value:
                    # Extract dependent task ID
                    try:
                        dep_id = int(value.split("-")[1])
                        # Ensure dependent task ID exists and is not itself
                        if dep_id != task_id and dep_id in [t.get("id") for t in tasks]:
                            if dep_id not in deps:
                                deps.append(dep_id)
                    except (ValueError, IndexError):
                        # If parsing fails, ignore this dependency
                        pass
            
            # If task has dependencies, use dependency list; otherwise use [-1] to indicate no dependencies
            if deps:
                task["dep"] = deps
            else:
                task["dep"] = [-1]
        return tasks
    
    def _can_execute(self, task: dict, results: dict, executed: set) -> bool:
        """Check if task can be executed (dependencies satisfied)."""
        deps = task.get("dep", [-1])
        # If dependency is [-1], means no dependencies, can execute
        if deps == [-1] or (isinstance(deps, list) and len(deps) == 1 and deps[0] == -1):
            return True
        # Check if all dependencies have been executed
        # Filter out -1 and invalid dependency IDs
        valid_deps = [dep_id for dep_id in deps if dep_id != -1 and dep_id in executed]
        # If all valid dependencies have been executed, or there are no valid dependencies, can execute
        return len(valid_deps) == len([d for d in deps if d != -1]) if deps else True
    
    def _run_task(
        self,
        task: dict,
        results: dict,
        user_input: str
    ) -> dict[str, object]:
        """
        Executes a single task.
        
        Args:
            task: Task dictionary.
            results: Dictionary of already executed task results.
            user_input: Original user input for context.
        
        Returns:
            Task execution result.
        """
        task_id = task["id"]
        task_type = task["task"]
        args = task.get("args", {})
        deps = task.get("dep", [-1])
        
        # Handle dependencies: get resources from dependent tasks
        if deps and deps != [-1] and not (isinstance(deps, list) and len(deps) == 1 and deps[0] == -1):
            for dep_id in deps:
                if dep_id == -1:
                    continue  # Skip -1
                if dep_id in results:
                    dep_result = results[dep_id].get("inference result", {})
                    # Extract generated resources
                    for resource_type in ["text", "image", "audio"]:
                        resource_key = f"generated {resource_type}"
                        if resource_key in dep_result:
                            # Check if args has corresponding GENERATED tag
                            for key, value in args.items():
                                if isinstance(value, str) and f"<GENERATED>-{dep_id}" in value:
                                    args[key] = dep_result[resource_key]
                # else:
                # Dependency result not found, skip this dependency
        
        # Clean invalid parameters: some task types should not have certain parameters
        if task_type == "text-to-image":
            # text-to-image tasks only need text parameter, not image parameter
            if "image" in args:
                # If image is a GENERATED tag, task parsing is incorrect, remove it
                if isinstance(args.get("image"), str) and "<GENERATED>" in args["image"]:
                    del args["image"]
        elif task_type in ["text-generation", "text2text-generation", "summarization", "translation", "conversational"]:
            # These tasks only need text parameter
            if "image" in args and isinstance(args.get("image"), str) and "<GENERATED>" in args["image"]:
                # If image is a GENERATED tag but task doesn't need image, remove it
                del args["image"]
            if "audio" in args and isinstance(args.get("audio"), str) and "<GENERATED>" in args["audio"]:
                del args["audio"]
        
        # Handle resource paths
        for resource in ["image", "audio"]:
            if resource in args and args[resource]:
                path = args[resource]
                # Skip GENERATED tags, they will be replaced during dependency processing
                if isinstance(path, str) and "<GENERATED>" in path:
                    continue
                if not path.startswith("http") and not path.startswith("outputs/") and not path.startswith("public/"):
                    if not path.startswith("/"):
                        # Check if file exists, if not try outputs directory
                        from pathlib import Path
                        if not Path(path).exists():
                            args[resource] = f"outputs/{path}"
                        else:
                            args[resource] = path
        
        # Select model
        model_id, hosted_on = self._choose_model_for_task(task_type, args, user_input)
        
        if not model_id:
            return {
                "task": task,
                "choose model result": {},
                "inference result": {"error": "No available model found"}
            }
        
        # Execute inference
        try:
            inference_result = self._model_inference(model_id, args, hosted_on, task_type, user_input)
        except Exception as e:
            # Catch exceptions during inference
            inference_result = {"error": {"message": str(e)}}
        
        return {
            "task": task,
            "choose model result": {"id": model_id, "reason": "Selected from available models"},
            "inference result": inference_result
        }
    
    def _choose_model_for_task(
        self,
        task_type: str,
        args: dict,
        user_input: str
    ) -> tuple[str, str]:
        """
        Chooses the most suitable model for a given task.
        
        Args:
            task_type: Type of the task.
            args: Arguments for the task.
            user_input: Original user input for context.
        
        Returns:
            Tuple of (model_id, hosted_on) or (None, None) if no model found.
        """
        # Special handling: ControlNet tasks
        if task_type.endswith("-text-to-image") or task_type.endswith("-control"):
            if self._inference_mode != "huggingface" and self._local_adapter:
                if task_type.endswith("-text-to-image"):
                    control = task_type.split("-")[0]
                    model_id = f"lllyasviel/sd-controlnet-{control}"
                else:
                    model_id = task_type
                return (model_id, "local")
            else:
                return (None, None)
        
        # Special handling: Tasks that ChatGPT can handle
        # For text generation tasks, ChatGPT usually performs better, use ChatGPT directly
        # Note: If user wants to use HuggingFace models, comment out this section
        if task_type in [
            "summarization", "translation", "conversational",
            "text-generation", "text2text-generation"
        ]:
            return ("ChatGPT", "chatgpt")
        
        # Get candidate models from model mapping
        if task_type not in self._models_map:
            return (None, None)
        
        candidates = self._models_map[task_type][:10]
        
        if not candidates:
            return (None, None)
        
        # Get available models
        available_models = self._model_selector.get_available_models(
            candidates,
            topk=self._num_candidate_models,
            inference_mode=self._inference_mode
        )
        
        all_available = available_models["local"] + available_models["huggingface"]
        
        if not all_available:
            # Fallback strategy: if model check fails, try using ChatGPT (if task type supports it)
            if task_type in [
                "summarization", "translation", "conversational",
                "text-generation", "text2text-generation"
            ]:
                return ("ChatGPT", "chatgpt")
            
            # For other task types, try using the first candidate model directly
            # Note: model may not actually be available
            first_candidate = candidates[0]
            model_id = first_candidate["id"]
            
            # Select hosting location based on inference mode
            if self._inference_mode == "local" and self._local_adapter:
                return (model_id, "local")
            elif self._inference_mode == "huggingface" and self._hf_adapter:
                return (model_id, "huggingface")
            else:
                # Hybrid mode, prefer huggingface
                if self._hf_adapter:
                    return (model_id, "huggingface")
                elif self._local_adapter:
                    return (model_id, "local")
                else:
                    # If all adapters are unavailable, use ChatGPT for text tasks
                    if task_type in ["text-generation", "text2text-generation", "summarization", "translation", "conversational"]:
                        return ("ChatGPT", "chatgpt")
                    return (None, None)
        
        if len(all_available) == 1:
            model_id = all_available[0]
            hosted_on = "local" if model_id in available_models["local"] else "huggingface"
            return (model_id, hosted_on)
        
        # Multiple candidate models, use LLM to select
        # Simplified handling here: directly select the first available model
        # In practice, should call ModelChooser
        model_id = all_available[0]
        hosted_on = "local" if model_id in available_models["local"] else "huggingface"
        return (model_id, hosted_on)
    
    def _model_inference(
        self,
        model_id: str,
        data: dict,
        hosted_on: str,
        task: str,
        user_input: str = ""
    ) -> dict[str, object]:
        """
        Performs inference using the selected model.
        
        Args:
            model_id: ID of the model to use.
            data: Input data for inference.
            hosted_on: Where the model is hosted ("local" or "huggingface" or "chatgpt").
            task: Type of the task.
            user_input: Original user input for context.
        
        Returns:
            Inference result.
        """
        if hosted_on == "chatgpt":
            # ChatGPT handling: use OpenAI model to generate text/code
            from masfactory.adapters.model import ModelResponseType
            
            # Build prompt
            if task == "text-generation" or task == "text2text-generation":
                user_text = data.get("text", "")
                # Use the original user input passed in for better context understanding
                original_user_input = user_input
                
                # For code generation tasks, use more explicit prompts
                # Check for code-related keywords
                if any(keyword in user_text.lower() for keyword in ["code", "program", "generate", "write", "create"]):
                    # If original user input contains more specific requirements, use original input
                    if original_user_input and len(original_user_input) > len(user_text):
                        context_prompt = f"""User's original request: {original_user_input}

Current task: {user_text}

Please generate code directly based on the user's original request, do not ask the user. Requirements:
1. Generate complete, runnable code directly
2. Include necessary comments
3. Do not ask the user any questions, generate code directly
4. If UI is involved, use common UI frameworks (such as Python's tkinter, PyQt, or Web's HTML/CSS/JavaScript)
5. Code should be complete and directly runnable
6. If user requests a specific type of game (such as Gomoku, Snake, etc.), generate the corresponding type of game code"""
                    else:
                        context_prompt = f"""Please generate code directly, do not ask the user. Generate complete code according to the following requirements:

{user_text}

Requirements:
1. Generate complete, runnable code directly
2. Include necessary comments
3. Do not ask the user any questions, generate code directly
4. If UI is involved, use common UI frameworks (such as Python's tkinter, PyQt, or Web's HTML/CSS/JavaScript)
5. Code should be complete and directly runnable"""
                    prompt = context_prompt
                else:
                    prompt = user_text
            elif task == "summarization":
                prompt = f"Please summarize the following content:\n{data.get('text', '')}"
            elif task == "translation":
                prompt = f"Please translate the following content:\n{data.get('text', '')}"
            elif task == "conversational":
                prompt = data.get("text", "")
            else:
                prompt = data.get("text", "")
            
            # Call OpenAI model
            try:
                messages = [
                    {"role": "system", "content": "You are a helpful coding assistant. Always generate complete, runnable code directly without asking questions."},
                    {"role": "user", "content": prompt}
                ]
                # invoke method requires explicit tools parameter (can be None)
                response = self._model.invoke(messages=messages, tools=None)
                
                # Handle tool calls (if needed)
                max_tool_calls = 5
                tool_call_count = 0
                while response["type"] != ModelResponseType.CONTENT:
                    if response["type"] == ModelResponseType.TOOL_CALL:
                        tool_call_count += 1
                        if tool_call_count > max_tool_calls:
                            return {"error": {"message": "Exceeded maximum tool calls"}}
                        # For code generation tasks, tool calls are usually not needed, return error directly
                        return {"error": {"message": "Tool calls not supported for code generation"}}
                    else:
                        return {"error": {"message": "Unexpected response type from model"}}
                
                # Get generated content
                generated_text = response["content"]
                return {"generated text": generated_text}
            except Exception as e:
                return {"error": {"message": str(e)}}
        
        if hosted_on == "local" and self._local_adapter:
            return self._local_adapter.inference(model_id, data, task)
        elif hosted_on == "huggingface" and self._hf_adapter:
            return self._hf_adapter.inference(model_id, data, task)
        else:
            return {"error": {"message": f"Model {model_id} not available on {hosted_on}"}}

