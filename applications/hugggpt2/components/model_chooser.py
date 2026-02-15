"""Model selection component.

This module provides the ModelChooser class, which selects the most appropriate
model from a list of candidates for a given task.
"""

import json
import re
from typing import Dict, Optional
from pathlib import Path
from masfactory import Agent
from masfactory.core.message import JsonMessageFormatter

# Import prompts
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from prompts import CHOOSE_MODEL_TPROMPT, CHOOSE_MODEL_PROMPT


class ModelChooser(Agent):
    """Model selection node: selects the most suitable model for a task.
    
    This agent analyzes task requirements and model capabilities to choose
    the best model from available candidates.
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
        """Initialize model chooser.
        
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
        
        instructions = CHOOSE_MODEL_TPROMPT
        # CHOOSE_MODEL_PROMPT uses {{input}}, {{task}}, {{metas}}
        # We need to adapt to {{user_input}}, {{task}}, {{candidate_models}}
        prompt_template = CHOOSE_MODEL_PROMPT.replace("{{input}}", "{{user_input}}").replace("{{metas}}", "{{candidate_models}}")
        
        super().__init__(
            name=name,
            model=model,
            instructions=instructions,
            prompt_template=prompt_template,
            formatters=JsonMessageFormatter(),
            pull_keys=pull_keys or {
                "user_input": "User input",
                "task": "Task description",
                "candidate_models": "Candidate model list"
            },
            push_keys=push_keys or {
                "chosen_model": "Selected model information (JSON format)"
            },
            **kwargs
        )
        self._demos = demos
    
    def _forward(self, input: dict[str, object]) -> dict[str, object]:
        """
        Executes model selection.
        
        Args:
            input: Input dictionary.
        
        Returns:
            Output dictionary containing chosen_model.
        """
        result = super()._forward(input)
        
        # Parse selected model
        chosen_str = result.get("chosen_model", "{}")
        if isinstance(chosen_str, str):
            # Try to extract JSON
            json_match = re.search(r'\{[^}]+\}', chosen_str)
            if json_match:
                try:
                    chosen = json.loads(json_match.group())
                except (json.JSONDecodeError, ValueError):
                    chosen = self._extract_model_info(chosen_str)
            else:
                chosen = self._extract_model_info(chosen_str)
        else:
            chosen = chosen_str
        
        return {"chosen_model": chosen}
    
    def _extract_model_info(self, text: str) -> dict[str, object]:
        """
        Extracts model information from text.
        
        Args:
            text: Text containing model information.
        
        Returns:
            Model information dictionary.
        """
        result = {"id": "", "reason": ""}
        
        # Try to extract ID
        id_match = re.search(r'"id"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
        if id_match:
            result["id"] = id_match.group(1)
        
        # Try to extract reason
        reason_match = re.search(r'"reason"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
        if reason_match:
            result["reason"] = reason_match.group(1)
        
        return result

