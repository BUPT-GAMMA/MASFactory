"""Task parsing component.

This module provides the TaskParser class, which parses user input into
a structured list of tasks with dependencies and arguments.
"""

import json
from typing import Dict, Optional
from pathlib import Path
from masfactory import Agent
from masfactory.core.message import JsonMessageFormatter

# Import prompts
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from prompts import PARSE_TASK_TPROMPT, PARSE_TASK_PROMPT


class TaskParser(Agent):
    """Task parsing node: parses user input into a task list.
    
    This agent analyzes user input and breaks it down into a structured list
    of tasks with dependencies, IDs, and required arguments.
    """
    
    def __init__(
        self,
        name: str,
        model,
        demos_path: str,
        pull_keys: Optional[Dict[str, str]] = None,
        push_keys: Optional[Dict[str, str]] = None,
        **kwargs
    ):
        """Initialize task parser.
        
        Args:
            name: Node name.
            model: Model adapter.
            demos_path: Path to demo data file.
            pull_keys: Input keys.
            push_keys: Output keys.
        """
        # Read demo data
        try:
            with open(demos_path, 'r', encoding='utf-8') as f:
                demos_content = f.read()
                demos = json.loads(demos_content)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            demos = []
        
        # Build instructions
        instructions = PARSE_TASK_TPROMPT
        
        # Build prompt template
        # PARSE_TASK_PROMPT uses {{context}} and {{input}}, need to adapt
        prompt_template = PARSE_TASK_PROMPT.replace("{{input}}", "{{user_input}}")
        
        super().__init__(
            name=name,
            model=model,
            instructions=instructions,
            prompt_template=prompt_template,
            formatters=JsonMessageFormatter(),
            pull_keys=pull_keys or {
                "user_input": "User's input task description",
                "context": "Conversation history context"
            },
            push_keys=push_keys or {
                "tasks": "Parsed task list (JSON format)",
                "user_input": "User input (passed through)"
            },
            **kwargs
        )
        self._demos = demos
    
    def _forward(self, input: dict[str, object]) -> dict[str, object]:
        """
        Executes task parsing.
        
        Args:
            input: Input dictionary containing user_input and context.
        
        Returns:
            Output dictionary containing tasks.
        """
        # Call parent class _forward method
        result = super()._forward(input)
        
        # Parse tasks field
        tasks_str = result.get("tasks", "[]")
        if isinstance(tasks_str, str):
            try:
                tasks = json.loads(tasks_str)
            except (json.JSONDecodeError, ValueError):
                tasks = []
        else:
            tasks = tasks_str
        
        # Validate and fix task format
        if not isinstance(tasks, list):
            tasks = []
        
        # Ensure each task has necessary fields
        for task in tasks:
            if "id" not in task:
                task["id"] = len(tasks)
            if "dep" not in task:
                task["dep"] = [-1]
            if "args" not in task:
                task["args"] = {}
            if "task" not in task:
                task["task"] = "unknown"
        
        # Return both tasks and user_input to pass to next node
        # user_input is obtained from input and passed through, no need for LLM to generate
        return {
            "tasks": tasks,
            "user_input": input.get("user_input", "")
        }

