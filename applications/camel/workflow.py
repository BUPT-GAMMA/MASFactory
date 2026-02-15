"""CAMEL Role-Playing workflow definition.

This module defines the workflow for CAMEL role-playing, which creates a multi-agent
conversation system where AI User and AI Assistant agents collaborate to solve tasks.
"""

from masfactory import RootGraph, OpenAIModel, Agent
from masfactory.components.custom_node import CustomNode
from conversation_loop import ConversationLoop
from camel_formatter import CamelMessageFormatter
from prompts import ROLE_GENERATION_PROMPT, ASSISTANT_PROMPT, USER_PROMPT
import os
import json
import re
import ast
from typing import Optional, Dict, Any


def _parse_dict_from_string(s: str) -> Optional[Dict[str, Any]]:
    """Parse dictionary from string, supporting both JSON and Python dict formats.
    
    Args:
        s: String containing dictionary representation (JSON or Python dict format).
    
    Returns:
        Parsed dictionary if successful, None otherwise.
    """
    if not isinstance(s, str) or not s.strip():
        return None
    s = s.strip()
    # Try parsing as JSON (double quotes)
    try:
        parsed = json.loads(s)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    # Try parsing as Python dictionary (single quotes, using ast.literal_eval)
    if s.startswith("{") and s.endswith("}"):
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError):
            pass
    return None


def create_camel_role_playing_workflow(
    model: Optional[OpenAIModel] = None,
    max_conversation_turns: int = 50,
    word_limit: int = 50,
    tools: Optional[list] = None,
    use_task_specify: bool = True,
) -> RootGraph:
    """Create CAMEL role-playing workflow.
    
    This function creates a complete workflow graph for CAMEL role-playing, including:
    - Task specification (optional)
    - Role generation
    - Role initialization
    - Conversation loop
    - Result collection
    
    Args:
        model: Model adapter. If None, will be read from environment variables.
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        tools: Optional list of tools for agents to use.
        use_task_specify: Whether to use task_specify step (default: True).
                         For already clear tasks (e.g., Q&A), can be set to False to skip.
    
    Returns:
        RootGraph: Configured workflow graph.
    
    Note:
        Task should be passed via graph.invoke({"task": "your task here"}), not as a parameter.
    """
    # Create RootGraph
    graph = RootGraph(name="camel", attributes={})
    
    if model is None:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.csun.site/v1/")
        model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set and model parameter not provided")
        model = OpenAIModel(api_key=api_key, base_url=base_url, model_name=model_name)
    
    # Create task_specify node (optional)
    if use_task_specify:
        task_specify_instructions = """You are a task specifier. Your job is to refine vague task descriptions into clear, specific, and actionable tasks.

Here is a task: {task}.
Please make it more specific, but DO NOT over-complicate simple tasks. 
- If the task is already simple and clear (like "create an adder"), keep it simple and focused on the core functionality.
- Only add essential requirements (like basic error handling if it's a user input task).
- DO NOT add unnecessary features like loops, exit mechanisms, or complex UI unless explicitly requested.

Please reply with the specified task in {word_limit} words or less. Do not add anything else.

Please provide only the specified task description, without any additional explanation."""
        
        task_specify_formatter = CamelMessageFormatter(output_key="specified_task", required_keys=None)
        
        class TaskSpecifyAgent(Agent):
            def _forward(self, input: dict[str, object]) -> dict:
                if hasattr(self._out_formatter, '_required_keys'):
                    output_keys_set = set(self.output_keys.keys())
                    self._out_formatter._required_keys = output_keys_set
                return super()._forward(input)
        
        task_specify_node = graph.create_node(
            TaskSpecifyAgent,
            name="task_specifier",
            model=model,
            instructions=task_specify_instructions,
            formatters=task_specify_formatter,
            pull_keys={"task": "Original vague task description from user"},
            push_keys={"specified_task": "Refined and specified task description"},
            attributes={"word_limit": word_limit},
        )
    else:
        # If task_specify is not used, create a pass-through node
        def task_pass_through_forward(input_dict: dict[str, object]) -> dict[str, object]:
            # Directly pass task as specified_task
            return {"specified_task": input_dict.get("task", "")}
        
        task_specify_node = graph.create_node(
            CustomNode,
            name="task_specifier",
            forward=task_pass_through_forward,
            pull_keys={"task": "Original task description from user"},
            push_keys={"specified_task": "Task description (passed through without specification)"},
        )
    
    role_generation_instructions = """You are a role generator. Given a specific task, you need to suggest two complementary roles: 
one for the AI Assistant (expert who helps) and one for the AI User (person who needs help)."""
    
    output_key = "assistant_role"
    role_generation_formatter = CamelMessageFormatter(output_key=output_key, required_keys=None)
    
    class RoleGenerationAgent(Agent):
        def _forward(self, input: dict[str, object]) -> dict:
            if hasattr(self._out_formatter, '_required_keys'):
                output_keys_set = set(self.output_keys.keys())
                self._out_formatter._required_keys = output_keys_set
            
            task = input.get("specified_task", input.get("task", ""))
            role_generation_prompt = ROLE_GENERATION_PROMPT.format(task=task)
            
            original_instructions = self._instructions
            self._instructions = f"""You are a role generator. Your job is to suggest two complementary roles for completing a task.

{role_generation_prompt}

Please respond with valid JSON only, containing "assistant_role" and "user_role" keys."""
            
            result = super()._forward({"specified_task": task, "role_generation_request": role_generation_prompt})
            self._instructions = original_instructions
            
            assistant_role = ""
            user_role = ""
            for key, value in result.items():
                if isinstance(value, dict):
                    if "assistant_role" in value and not assistant_role:
                        assistant_role = str(value.get("assistant_role", "")).strip()
                    if "user_role" in value and not user_role:
                        user_role = str(value.get("user_role", "")).strip()
                    if assistant_role and user_role:
                        break
                elif isinstance(value, str) and value.strip():
                    if key == "assistant_role" and not assistant_role:
                        parsed_dict = _parse_dict_from_string(value)
                        assistant_role = str(parsed_dict.get("assistant_role", "")) if parsed_dict else value.strip()
                    elif key == "user_role" and not user_role:
                        parsed_dict = _parse_dict_from_string(value)
                        user_role = str(parsed_dict.get("user_role", "")) if parsed_dict else value.strip()
                    elif not assistant_role or not user_role:
                        parsed_dict = _parse_dict_from_string(value)
                        if parsed_dict:
                            if "assistant_role" in parsed_dict and not assistant_role:
                                assistant_role = str(parsed_dict.get("assistant_role", "")).strip()
                            if "user_role" in parsed_dict and not user_role:
                                user_role = str(parsed_dict.get("user_role", "")).strip()
                            if assistant_role and user_role:
                                break
            
            if assistant_role and user_role:
                return {
                    "assistant_role": assistant_role,
                    "user_role": user_role,
                    "specified_task": task,
                }
            json_pattern = r'```json\s*(\{.*?\})\s*```|(\{[^{}]*"assistant_role"[^{}]*"user_role"[^{}]*\})'
            for value in result.values():
                if isinstance(value, str) and ("assistant_role" in value or "user_role" in value):
                    match = re.search(json_pattern, value, re.DOTALL)
                    if match:
                        try:
                            json_str = match.group(1) or match.group(2)
                            parsed = json.loads(json_str)
                            if isinstance(parsed, dict):
                                if not assistant_role:
                                    assistant_role = str(parsed.get("assistant_role", "")).strip()
                                if not user_role:
                                    user_role = str(parsed.get("user_role", "")).strip()
                                if assistant_role and user_role:
                                    break
                        except (json.JSONDecodeError, ValueError):
                            pass
            
            return {
                "assistant_role": assistant_role if assistant_role else "AI Assistant",
                "user_role": user_role if user_role else "AI User",
                "specified_task": task,
            }
    
    role_generation_node = graph.create_node(
        RoleGenerationAgent,
        name="role_generator",
        model=model,
        instructions=role_generation_instructions,
        formatters=role_generation_formatter,
        pull_keys={"specified_task": "Specified task from task specifier"},
        push_keys={
            "assistant_role": "Generated role name for AI Assistant",
            "user_role": "Generated role name for AI User",
            "specified_task": "Specified task to pass through",
        },
    )
    
    def role_initialization_forward(input_dict: dict[str, object]) -> dict[str, object]:
        """Generate system messages for AI User and AI Assistant based on roles and task."""
        task = input_dict.get("specified_task", input_dict.get("task", ""))
        assistant_role_raw = input_dict.get("assistant_role", "")
        user_role_raw = input_dict.get("user_role", "")
        
        def extract_role(value: Any, role_key: str) -> str:
            if isinstance(value, dict):
                return str(value.get(role_key, "")).strip()
            elif isinstance(value, str):
                parsed_dict = _parse_dict_from_string(value)
                if parsed_dict:
                    return str(parsed_dict.get(role_key, "")).strip()
                return value.strip()
            return str(value).strip()
        
        assistant_role = extract_role(assistant_role_raw, "assistant_role")
        user_role = extract_role(user_role_raw, "user_role")
        
        if not assistant_role or not user_role:
            for value in input_dict.values():
                if isinstance(value, dict):
                    if "assistant_role" in value and not assistant_role:
                        assistant_role = str(value.get("assistant_role", "")).strip()
                    if "user_role" in value and not user_role:
                        user_role = str(value.get("user_role", "")).strip()
                    if assistant_role and user_role:
                        break
                elif isinstance(value, str):
                    parsed_dict = _parse_dict_from_string(value)
                    if parsed_dict:
                        if "assistant_role" in parsed_dict and not assistant_role:
                            assistant_role = str(parsed_dict.get("assistant_role", "")).strip()
                        if "user_role" in parsed_dict and not user_role:
                            user_role = str(parsed_dict.get("user_role", "")).strip()
                        if assistant_role and user_role:
                            break
        
        # Check if GAIA specific prompts should be used (via environment variable or task content)
        use_gaia_prompts = os.getenv("USE_GAIA_PROMPTS", "false").lower() == "true"
        if not use_gaia_prompts:
            # Check if task description contains GAIA related keywords
            task_lower = str(task).lower()
            if any(keyword in task_lower for keyword in ["gaia", "read_file", "calculate", "read_csv", "available tools"]):
                use_gaia_prompts = True
        
        if use_gaia_prompts:
            try:
                # Try importing GAIA specific prompts
                import sys
                from pathlib import Path
                gaia_prompts_path = Path(__file__).parent / "gaia" / "gaia_prompts.py"
                if gaia_prompts_path.exists():
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("gaia_prompts", gaia_prompts_path)
                    gaia_prompts = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(gaia_prompts)
                    assistant_sys_prompt = gaia_prompts.GAIA_ASSISTANT_PROMPT.format(
                        assistant_role=assistant_role,
                        user_role=user_role,
                        task=task
                    )
                    user_sys_prompt = gaia_prompts.GAIA_USER_PROMPT.format(
                        user_role=user_role,
                        assistant_role=assistant_role,
                        task=task
                    )
                else:
                    raise ImportError("GAIA prompts file not found")
            except (ImportError, Exception) as e:
                # If import fails, use default prompts
                assistant_sys_prompt = ASSISTANT_PROMPT.format(
                    assistant_role=assistant_role,
                    user_role=user_role,
                    task=task
                )
                user_sys_prompt = USER_PROMPT.format(
                    user_role=user_role,
                    assistant_role=assistant_role,
                    task=task
                )
        else:
            assistant_sys_prompt = ASSISTANT_PROMPT.format(
                assistant_role=assistant_role,
                user_role=user_role,
                task=task
            )
            user_sys_prompt = USER_PROMPT.format(
                user_role=user_role,
                assistant_role=assistant_role,
                task=task
            )
        
        return {
            "assistant_system_prompt": assistant_sys_prompt,
            "user_system_prompt": user_sys_prompt,
            "assistant_role_name": assistant_role,
            "user_role_name": user_role,
            "task": task,
        }
    
    role_init_node = graph.create_node(
        CustomNode,
        name="role_initializer",
        forward=role_initialization_forward,
        pull_keys={
            "assistant_role": "Generated role name for AI Assistant",
            "user_role": "Generated role name for AI User",
            "specified_task": "Specified task from task specifier",
        },
        push_keys={
            "assistant_system_prompt": "System prompt for AI Assistant",
            "user_system_prompt": "System prompt for AI User",
            "task": "Final task to be completed",
            "assistant_role_name": "Name of AI Assistant role",
            "user_role_name": "Name of AI User role",
        },
    )
    
    conversation_loop = graph.create_node(
        ConversationLoop,
        name="conversation_loop",
        model=model,
        max_iterations=max_conversation_turns,
        tools=tools,
        pull_keys={
            "assistant_system_prompt": "System prompt for AI Assistant",
            "user_system_prompt": "System prompt for AI User",
            "assistant_role_name": "Name of AI Assistant role",
            "user_role_name": "Name of AI User role",
            "task": "Final task to be completed",
        },
        push_keys={
            "user_message": "Final message from AI User",
            "assistant_message": "Final message from AI Assistant",
            "conversation_history": "Complete conversation history",
            "assistant_role_name": "Name of AI Assistant role",
            "user_role_name": "Name of AI User role",
            "task": "Final task to be completed",
        },
    )
    
    graph.edge_from_entry(
        receiver=task_specify_node,
        keys={"task": "Original task description from user"},
    )
    
    graph.create_edge(
        sender=task_specify_node,
        receiver=role_generation_node,
        keys={"specified_task": "Task description (specified or passed through)"},
    )
    
    graph.create_edge(
        sender=role_generation_node,
        receiver=role_init_node,
        keys={
            "assistant_role": "Generated role name for AI Assistant",
            "user_role": "Generated role name for AI User",
            "specified_task": "Specified task from task specifier",
        },
    )
    
    graph.create_edge(
        sender=role_init_node,
        receiver=conversation_loop,
        keys={
            "assistant_system_prompt": "System prompt for AI Assistant",
            "user_system_prompt": "System prompt for AI User",
            "assistant_role_name": "Name of AI Assistant role",
            "user_role_name": "Name of AI User role",
            "task": "Final task to be completed",
        },
    )
    
    role_info_collector = graph.create_node(
        CustomNode,
        name="role_info_collector",
        forward=lambda input_dict: {
            "conversation_result": {
                "final_user_message": input_dict.get("user_message", ""),
                "final_assistant_message": input_dict.get("assistant_message", ""),
                "conversation_history": input_dict.get("conversation_history", []),
                "task_completed": "<CAMEL_TASK_DONE>" in str(input_dict.get("user_message", "")).upper(),
                "assistant_role_name": input_dict.get("assistant_role_name", ""),
                "user_role_name": input_dict.get("user_role_name", ""),
                "task": input_dict.get("task", ""),
            }
        },
        pull_keys={
            "user_message": "Final message from AI User",
            "assistant_message": "Final message from AI Assistant",
            "conversation_history": "Complete conversation history",
            "assistant_role_name": "Name of AI Assistant role",
            "user_role_name": "Name of AI User role",
            "task": "Final task to be completed",
        },
        push_keys={"conversation_result": "Final conversation result with role info"},
    )
    
    graph.create_edge(
        sender=conversation_loop,
        receiver=role_info_collector,
        keys={
            "user_message": "Final message from AI User",
            "assistant_message": "Final message from AI Assistant",
            "conversation_history": "Complete conversation history",
            "assistant_role_name": "Name of AI Assistant role",
            "user_role_name": "Name of AI User role",
            "task": "Final task to be completed",
        },
    )
    
    result_collector = role_info_collector
    graph.edge_to_exit(
        sender=result_collector,
        keys={"conversation_result": "Final conversation result with completion status"},
    )
    
    return graph

