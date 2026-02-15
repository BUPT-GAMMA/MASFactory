from __future__ import annotations

from masfactory.adapters.model import Model
from masfactory.components.controls.base_switch import BaseSwitch


class AgentSwitch(BaseSwitch[str]):
    """LLM-based routing switch.

    Each out edge can be bound to a natural-language condition. The model
    evaluates the input message against each condition and routes only to
    the edges whose condition is satisfied.

    Important: non-selected edges must be closed; otherwise downstream nodes
    may never become ready (open + uncongested in-edges keep a node blocked).
    """

    def __init__(
        self,
        name: str,
        model: Model,
        pull_keys: dict[str, dict|str] | None = None,
        push_keys: dict[str, dict|str] | None = None,
        attributes: dict[str, object] | None = None,
        routes: dict[str, str] | None = None,
    ):
        """Create an AgentSwitch.

        Args:
            name: Node name.
            model: Model adapter used to evaluate routing conditions.
            pull_keys: Attribute pull rule for this node.
            push_keys: Attribute push rule for this node.
            attributes: Optional default attributes local to this node.
            routes: Optional declarative routing rules as `receiver_node_name -> condition_text`.
        """
        super().__init__(
            name=name,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes,
            routes=routes,
        )
        self._model = model
        if self._model is None:
            raise ValueError("model must be provided")

        self._prompt = """
You are a precise, rule-based evaluation agent. Your task is to analyze the user's input, which contains one ANSWER and a single CONDITION.
You must determine if the ANSWER satisfies the CONDITION.
Your response MUST be a single word: either 'YES' or 'NO'.
DO NOT include any explanations, commentary, or any text other than the single word 'YES' or 'NO'.

---
Example 1:

USER INPUT:
ANSWER:
The file has been successfully uploaded to the server.
CONDITION:
The answer must contain the word "successfully".

YOUR EXPECTED OUTPUT:
YES

---
Example 2:

USER INPUT:
ANSWER:
An error occurred during the process.
CONDITION:
The answer must contain the word "successfully".

YOUR EXPECTED OUTPUT:
NO
""".strip()

    def _evaluate_condition(self, condition: str, message: dict[str, object]) -> bool:
        llm_input = f"""USER INPUT:
ANSWER:
{message}
CONDITION:
{condition}
"""
        messages = [
            {"role": "system", "content": self._prompt},
            {"role": "user", "content": llm_input},
        ]
        response_dict = self._model.invoke(messages=messages, tools=None)
        response = response_dict.get("content", "")
        return isinstance(response, str) and ("YES" in response.upper())
