"""Response generation component.

This module provides the ResponseGenerator class, which integrates task execution
results into a coherent final response for the user.
"""

import json
from typing import Dict, Optional
from pathlib import Path
from masfactory import Agent
from masfactory.core.message import JsonMessageFormatter

# Import prompts
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from prompts import RESPONSE_RESULTS_TPROMPT, RESPONSE_RESULTS_PROMPT


class ResponseGenerator(Agent):
    """Response generation node: integrates task results into final response.
    
    This agent takes task execution results and generates a comprehensive,
    user-friendly response that explains the workflow and results.
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
        """Initialize response generator.
        
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
        
        instructions = RESPONSE_RESULTS_TPROMPT
        # RESPONSE_RESULTS_PROMPT uses {{input}}, but our input is user_input
        # Create an adapted prompt template
        prompt_template = RESPONSE_RESULTS_PROMPT.replace("{{input}}", "{{user_input}}")
        
        super().__init__(
            name=name,
            model=model,
            instructions=instructions,
            prompt_template=prompt_template,
            formatters=JsonMessageFormatter(),
            pull_keys=pull_keys or {
                "user_input": "User input",
                "task_results": "Task execution results"
            },
            push_keys=push_keys or {
                "response": "Final response text"
            },
            **kwargs
        )
        self._demos = demos
    
    def _forward(self, input: dict[str, object]) -> dict[str, object]:
        """
        Generates the final response.
        
        Args:
            input: Input dictionary containing user_input and task_results.
        
        Returns:
            Output dictionary containing response.
        """
        # Format task results
        task_results = input.get("task_results", {})
        formatted_results = self._format_results(task_results)
        
        # Build input, pass formatted_results as processes
        formatted_input = {
            "user_input": input.get("user_input", ""),
            "processes": formatted_results
        }
        
        # Call parent method (Agent will automatically handle prompt_template)
        result = super()._forward(formatted_input)
        
        # Extract response text
        response = result.get("response", "")
        if isinstance(response, dict):
            # If returned value is a dict, try to extract text
            response = response.get("message", str(response))
        elif not isinstance(response, str):
            response = str(response)
        
        # Ensure response language matches user input (if user input is Chinese, response should also be Chinese)
        user_input = input.get("user_input", "")
        if user_input and any('\u4e00' <= char <= '\u9fff' for char in user_input):
            # User input contains Chinese characters, ensure response is also in Chinese
            # If response is in English, prompt model to rewrite in Chinese (this is just a check, actual handling should be in prompts)
            pass  # Prompts have already handled language requirements
        
        return {"response": response}
    
    def _format_results(self, task_results: dict[str, object]) -> str:
        """
        Formats task results as a string.
        
        Args:
            task_results: Task results dictionary.
        
        Returns:
            Formatted result string (JSON format).
        """
        formatted = []
        
        # Sort task IDs: try converting to number, if fails sort as string
        def sort_key(item):
            task_id = item[0]
            if isinstance(task_id, (int, float)):
                return (0, int(task_id))
            try:
                return (0, int(task_id))
            except (ValueError, TypeError):
                import re
                numbers = re.findall(r'\d+', str(task_id))
                if numbers:
                    return (1, int(numbers[0]))
                return (2, str(task_id))
        
        for task_id, result in sorted(task_results.items(), key=sort_key):
            formatted.append({
                "task": result.get("task", {}),
                "choose model result": result.get("choose model result", {}),
                "inference result": result.get("inference result", {})
            })
        return json.dumps(formatted, indent=2, ensure_ascii=False)

