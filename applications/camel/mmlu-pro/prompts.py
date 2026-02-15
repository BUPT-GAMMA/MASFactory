"""MMLU-Pro evaluation prompt templates, reference GPQA implementation and adapt for 10 options."""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional


def escape_latex_braces(text: str) -> str:
    r"""
    Escape braces in LaTeX formulas to avoid being mistaken as format fields by CAMEL framework.
    
    Convert {number} or {alphanumeric} to {{number}} or {{alphanumeric}}
    But preserve braces in LaTeX commands like \left( and \right).
    
    Args:
        text: Text containing LaTeX formulas.
    
    Returns:
        Escaped text.
    """
    # Match braces in LaTeX formulas, but exclude already escaped {{...}} and braces in LaTeX commands
    def replace_brace(match):
        # Check if in LaTeX command (like \left(, \right), \frac{, etc.)
        before = text[:match.start()]
        # If preceded by backslash, might be LaTeX command, don't escape
        if before.endswith('\\'):
            return match.group(0)
        # Otherwise escape braces
        return '{{' + match.group(1) + '}}'
    
    # Match {number} or {alphanumeric combination}
    # But exclude already escaped {{...}} and \left(, \right), etc.
    pattern = r'(?<!\\)\{([0-9]+|[a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})'
    result = re.sub(pattern, replace_brace, text)
    return result


def load_chain_of_thought_examples() -> Dict:
    """Load chain-of-thought examples (if exist)."""
    # Try to load from MMLU-Pro dataset path
    base_path = Path(__file__).parent.parent.parent.parent.parent.parent
    possible_paths = [
        base_path / "datasets" / "mmlu-pro" / "prompts" / "chain_of_thought_examples.json",
        base_path / "datasets" / "mmlu-pro" / "chain_of_thought_examples.json",
        Path(__file__).parent / "chain_of_thought_examples.json",
    ]
    
    for path in possible_paths:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    
    # If not found, return empty dictionary
    return {"questions": []}


def generate_prompt_from_examples(json_data: Dict, with_explanations: bool = True) -> str:
    """Generate prompt text from example JSON."""
    output = ""
    for q in json_data.get("questions", []):
        output += f'Question: {q["question"]}\nChoices:\n'
        # MMLU-Pro has 10 options (A-J)
        for choice in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']:
            if choice in q.get("choices", {}):
                output += f'({choice}) {q["choices"][choice]}\n'
        
        if with_explanations:
            output += f"Let's think step by step: \n{q.get('explanation', '')}\n"
        
        correct_answer = q.get("correct_answer", "")
        if correct_answer:
            output += f'The correct answer is ({correct_answer})\n\n'
    
    return output


def zero_shot_prompt(
    question: str,
    choiceA: str, choiceB: str, choiceC: str, choiceD: str,
    choiceE: str, choiceF: str, choiceG: str, choiceH: str,
    choiceI: str, choiceJ: str
) -> str:
    """Generate zero-shot prompt."""
    # Escape LaTeX braces to avoid format field conflicts
    question = escape_latex_braces(question)
    choices = [choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ]
    choices = [escape_latex_braces(c) for c in choices]
    
    # Build complete question and option description
    # Build complete question and option description (ensure format is clear and won't be simplified)
    prompt = f"QUESTION:\n{question}\n\n"
    prompt += "ANSWER CHOICES:\n"
    for i, choice in enumerate(choices):
        if choice:  # Only show non-empty options
            letter = chr(ord('A') + i)  # A, B, C, ..., J
            prompt += f"({letter}) {choice}\n"
    
    prompt += "\nTASK: Determine the correct answer (A-J) and provide reasoning."
    return prompt


def chain_of_thought_prompt(
    question: str,
    choiceA: str, choiceB: str, choiceC: str, choiceD: str,
    choiceE: str, choiceF: str, choiceG: str, choiceH: str,
    choiceI: str, choiceJ: str
) -> str:
    """Generate chain-of-thought prompt (with examples)."""
    # Escape LaTeX braces to avoid format field conflicts
    question = escape_latex_braces(question)
    choices = [choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ]
    choices = [escape_latex_braces(c) for c in choices]
    
    prompt = "Here are some example questions from experts. An explanation is given before the final answer. Answer the final question yourself, giving your reasoning beforehand.\n"
    
    json_data = load_chain_of_thought_examples()
    prompt += generate_prompt_from_examples(json_data, with_explanations=True)
    
    prompt += f"Question: {question}"
    prompt += f"\nChoices:\n"
    for i, choice in enumerate(choices):
        letter = chr(ord('A') + i)  # A, B, C, ..., J
        prompt += f"({letter}) {choice}\n"
    prompt += "\nGive step by step reasoning before you answer, and when you're ready to answer, please use the format \"The correct answer is (insert answer here)\":\n"
    
    return prompt


def five_shot_prompt(
    question: str,
    choiceA: str, choiceB: str, choiceC: str, choiceD: str,
    choiceE: str, choiceF: str, choiceG: str, choiceH: str,
    choiceI: str, choiceJ: str
) -> str:
    """Generate 5-shot prompt (without explanations)."""
    # Escape LaTeX braces to avoid format field conflicts
    question = escape_latex_braces(question)
    choices = [choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ]
    choices = [escape_latex_braces(c) for c in choices]
    
    prompt = "Here are some example questions from experts. Answer the final question yourself, following the format of the previous questions exactly.\n"
    
    json_data = load_chain_of_thought_examples()
    prompt += generate_prompt_from_examples(json_data, with_explanations=False)
    
    prompt += f"Question: {question}"
    prompt += f"\nChoices:\n"
    for i, choice in enumerate(choices):
        letter = chr(ord('A') + i)  # A, B, C, ..., J
        prompt += f"({letter}) {choice}\n"
    prompt += "\nWhen you're ready to answer, please use the format \"The correct answer is (insert answer here).\""
    
    return prompt


def zero_shot_chain_of_thought_prompt(
    question: str,
    choiceA: str, choiceB: str, choiceC: str, choiceD: str,
    choiceE: str, choiceF: str, choiceG: str, choiceH: str,
    choiceI: str, choiceJ: str
) -> str:
    """Generate zero-shot chain-of-thought prompt (let model generate reasoning process itself)."""
    # Escape LaTeX braces to avoid format field conflicts
    question = escape_latex_braces(question)
    choices = [choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ]
    choices = [escape_latex_braces(c) for c in choices]
    
    prompt = f"What is the correct answer to this question: {question}"
    prompt += f"\n\nChoices:\n"
    for i, choice in enumerate(choices):
        letter = chr(ord('A') + i)  # A, B, C, ..., J
        prompt += f"({letter}) {choice}\n"
    prompt += "\n\nLet's think step by step: "
    # Note: This prompt requires model to generate reasoning process first, then generate answer
    # In actual use, may need two rounds of calls
    return prompt


def create_task_prompt(
    question: str,
    choiceA: str, choiceB: str, choiceC: str, choiceD: str,
    choiceE: str, choiceF: str, choiceG: str, choiceH: str,
    choiceI: str, choiceJ: str,
    prompt_type: str = "chain_of_thought"
) -> str:
    """
    Create task description based on prompt type.
    
    Args:
        question: Question text.
        choiceA-J: Ten options (A-J).
        prompt_type: Prompt type (zero_shot, chain_of_thought, 5_shot, zero_shot_chain_of_thought).
    
    Returns:
        Task description string.
    """
    if prompt_type == "zero_shot":
        base_prompt = zero_shot_prompt(question, choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ)
    elif prompt_type == "chain_of_thought":
        base_prompt = chain_of_thought_prompt(question, choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ)
    elif prompt_type == "5_shot":
        base_prompt = five_shot_prompt(question, choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ)
    elif prompt_type == "zero_shot_chain_of_thought":
        base_prompt = zero_shot_chain_of_thought_prompt(question, choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ)
    else:
        # Default use chain_of_thought
        base_prompt = chain_of_thought_prompt(question, choiceA, choiceB, choiceC, choiceD, choiceE, choiceF, choiceG, choiceH, choiceI, choiceJ)
    
    # Convert MMLU-Pro question to CAMEL task description
    # Ensure question and options are clearly visible in task description and won't be simplified by task_specify
    # Use explicit format markers to ensure task_specify doesn't delete key information
    task_description = f"""TASK: Answer the multiple-choice question below.

THE COMPLETE QUESTION AND ALL ANSWER CHOICES ARE PROVIDED HERE - DO NOT ASK FOR THEM:

{base_prompt}

CRITICAL: The QUESTION and all ANSWER CHOICES (A-J) are ALREADY PROVIDED above. Both User and Assistant can see them. DO NOT ask for the question or options.

YOUR JOB:
1. Analyze the question and all 10 answer choices (A-J)
2. Provide step-by-step reasoning
3. Select the correct answer (A, B, C, D, E, F, G, H, I, or J)

FOR THE ASSISTANT:
- Provide step-by-step reasoning before your final answer
- **CRITICAL**: After completing your reasoning, you MUST state your final answer in EXACTLY this format: "Final answer: X" where X is the letter (A-J)
- This format is required for automatic answer extraction. Example: "Final answer: I"
- When asked to output only the answer, respond with JUST the letter (A-J) on a separate line

FOR THE USER:
- Start with: "Instruction: Analyze the QUESTION and ANSWER CHOICES provided above and determine the correct answer. Input: None"
- After Assistant provides reasoning, give: "Instruction: Please output your final answer as just the letter (A-J) on a separate line. Input: None"
- After receiving the answer, send <CAMEL_TASK_DONE>
- DO NOT ask for the question or options - they are already in the task description above"""
    
    return task_description

