"""GPQA evaluation prompt templates, reference official implementation."""

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
    # Match pattern: {number} or {alphanumeric combination}, but not in \left( or \right) commands
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
    """Load chain-of-thought examples."""
    # Try to load from GPQA dataset path
    gpqa_path = Path(__file__).parent.parent.parent.parent.parent / "datasets" / "gpqa-main" / "gpqa-main" / "prompts" / "chain_of_thought_examples.json"
    
    if gpqa_path.exists():
        with open(gpqa_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    # If not found, return empty dictionary
    return {"questions": []}


def generate_prompt_from_examples(json_data: Dict, with_explanations: bool = True) -> str:
    """Generate prompt text from example JSON."""
    output = ""
    for q in json_data.get("questions", []):
        output += f'Question: {q["question"]}\nChoices:\n'
        for choice, value in q["choices"].items():
            output += f'({choice}) {value}\n'
        
        if with_explanations:
            output += f"Let's think step by step: \n{q.get('explanation', '')}\n"
        
        output += f'The correct answer is ({q["correct_answer"]})\n\n'
    
    return output


def zero_shot_prompt(question: str, choice1: str, choice2: str, choice3: str, choice4: str) -> str:
    """Generate zero-shot prompt."""
    # Escape LaTeX braces to avoid format field conflicts
    question = escape_latex_braces(question)
    choice1 = escape_latex_braces(choice1)
    choice2 = escape_latex_braces(choice2)
    choice3 = escape_latex_braces(choice3)
    choice4 = escape_latex_braces(choice4)
    
    prompt = f"What is the correct answer to this question: {question}"
    prompt += f"\n\nChoices:\n(A) {choice1}\n(B) {choice2}\n(C) {choice3}\n(D) {choice4}"
    prompt += f"\n\nFormat your response as follows: \"The correct answer is (insert answer here)\""
    return prompt


def chain_of_thought_prompt(question: str, choice1: str, choice2: str, choice3: str, choice4: str) -> str:
    """Generate chain-of-thought prompt (with examples)."""
    # Escape LaTeX braces to avoid format field conflicts
    question = escape_latex_braces(question)
    choice1 = escape_latex_braces(choice1)
    choice2 = escape_latex_braces(choice2)
    choice3 = escape_latex_braces(choice3)
    choice4 = escape_latex_braces(choice4)
    
    prompt = "Here are some example questions from experts. An explanation is given before the final answer. Answer the final question yourself, giving your reasoning beforehand.\n"
    
    json_data = load_chain_of_thought_examples()
    prompt += generate_prompt_from_examples(json_data, with_explanations=True)
    
    prompt += f"Question: {question}"
    prompt += f"\nChoices:\n(A) {choice1}\n(B) {choice2}\n(C) {choice3}\n(D) {choice4}"
    prompt += "\nGive step by step reasoning before you answer, and when you're ready to answer, please use the format \"The correct answer is (insert answer here)\":\n"
    
    return prompt


def five_shot_prompt(question: str, choice1: str, choice2: str, choice3: str, choice4: str) -> str:
    """Generate 5-shot prompt (without explanations)."""
    # Escape LaTeX braces to avoid format field conflicts
    question = escape_latex_braces(question)
    choice1 = escape_latex_braces(choice1)
    choice2 = escape_latex_braces(choice2)
    choice3 = escape_latex_braces(choice3)
    choice4 = escape_latex_braces(choice4)
    
    prompt = "Here are some example questions from experts. Answer the final question yourself, following the format of the previous questions exactly.\n"
    
    json_data = load_chain_of_thought_examples()
    prompt += generate_prompt_from_examples(json_data, with_explanations=False)
    
    prompt += f"Question: {question}"
    prompt += f"\nChoices:\n(A) {choice1}\n(B) {choice2}\n(C) {choice3}\n(D) {choice4}"
    prompt += "\nWhen you're ready to answer, please use the format \"The correct answer is (insert answer here).\""
    
    return prompt


def zero_shot_chain_of_thought_prompt(question: str, choice1: str, choice2: str, choice3: str, choice4: str) -> str:
    """Generate zero-shot chain-of-thought prompt (let model generate reasoning process itself)."""
    # Escape LaTeX braces to avoid format field conflicts
    question = escape_latex_braces(question)
    choice1 = escape_latex_braces(choice1)
    choice2 = escape_latex_braces(choice2)
    choice3 = escape_latex_braces(choice3)
    choice4 = escape_latex_braces(choice4)
    
    prompt = f"What is the correct answer to this question: {question}"
    prompt += f"\n\nChoices:\n(A) {choice1}\n(B) {choice2}\n(C) {choice3}\n(D) {choice4}"
    prompt += "\n\nLet's think step by step: "
    # Note: This prompt requires model to generate reasoning process first, then generate answer
    # In actual use, may need two rounds of calls
    return prompt


def create_task_prompt(
    question: str,
    choice1: str,
    choice2: str,
    choice3: str,
    choice4: str,
    prompt_type: str = "chain_of_thought"
) -> str:
    """
    Create task description based on prompt type.
    
    Args:
        question: Question text.
        choice1-4: Four options.
        prompt_type: Prompt type (zero_shot, chain_of_thought, 5_shot, zero_shot_chain_of_thought).
    
    Returns:
        Task description string.
    """
    if prompt_type == "zero_shot":
        base_prompt = zero_shot_prompt(question, choice1, choice2, choice3, choice4)
    elif prompt_type == "chain_of_thought":
        base_prompt = chain_of_thought_prompt(question, choice1, choice2, choice3, choice4)
    elif prompt_type == "5_shot":
        base_prompt = five_shot_prompt(question, choice1, choice2, choice3, choice4)
    elif prompt_type == "zero_shot_chain_of_thought":
        base_prompt = zero_shot_chain_of_thought_prompt(question, choice1, choice2, choice3, choice4)
    else:
        # Default use chain_of_thought
        base_prompt = chain_of_thought_prompt(question, choice1, choice2, choice3, choice4)
    
    # Convert GPQA question to CAMEL task description
    task_description = f"""Answer the following multiple-choice question. You need to:
1. Read and understand the question carefully
2. Analyze each choice option
3. Use your knowledge to reason through the problem step by step
4. Select the correct answer (A, B, C, or D)
5. Provide your reasoning and final answer

Here is the question:

{base_prompt}

IMPORTANT REQUIREMENTS FOR THE ASSISTANT:
- You MUST provide step-by-step reasoning before giving your final answer
- Be thorough in your reasoning, especially for complex scientific questions
- If you're uncertain, explain your thought process and make your best educated guess
- **CRITICAL**: After completing your reasoning, you MUST explicitly state your final answer in one of these formats:
  * "The correct answer is (A)" or "The correct answer is A"
  * "Answer: (A)" or "Answer: A"
  * "Final answer: (A)" or "Final answer: A"
  * Or simply "A" on a separate line
- When asked to output only the answer, you MUST respond with JUST the letter (A, B, C, or D) on a separate line, nothing else

IMPORTANT REQUIREMENTS FOR THE USER:
- After the Assistant has provided their reasoning and analysis, you MUST give this final instruction:
  "Instruction: Please output your final answer as just the letter (A, B, C, or D) on a separate line, with no additional text or explanation.
  Input: None"
- This ensures the answer is extracted easily
- After receiving the answer letter, immediately send <CAMEL_TASK_DONE>

CRITICAL FINAL ANSWER FORMAT:
The Assistant's final response should clearly indicate the answer letter. Acceptable formats include:
- "The correct answer is (A)"
- "Answer: A"
- "Final answer: (B)"
- Or simply:
A

The answer letter MUST be clearly stated, not just implied through calculations."""
    
    return task_description

