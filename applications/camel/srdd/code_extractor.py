"""Extract Python code from CAMEL framework output (SRDD version)."""

import re
from typing import Optional


def extract_python_code(text: str) -> str:
    """
    Extract Python code from text (complete software code, not function body).
    
    Priority extraction:
    1. Python code in markdown code blocks
    2. Directly included Python code
    
    Args:
        text: Text containing code.
    
    Returns:
        Extracted Python code string.
    """
    if not text:
        return ""
    
    text = text.strip()
    
    # Try to extract Python code from markdown code blocks
    # Match ```python or ``` code blocks
    code_block_patterns = [
        r'```python\s*\n(.*?)```',
        r'```\s*\n(.*?)```',
        r'```py\s*\n(.*?)```',
    ]
    
    for pattern in code_block_patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            # Return first matching code block
            code = matches[0].strip()
            if code:
                return code
    
    # Try to extract direct code (if contains keywords like import, def, class, etc.)
    if any(keyword in text for keyword in ['import ', 'from ', 'def ', 'class ', 'if __name__']):
        lines = text.split('\n')
        code_lines = []
        in_code_block = False
        
        for line in lines:
            stripped = line.strip()
            # Skip obvious non-code lines
            if stripped.startswith(('Solution:', 'Instruction:', 'Input:', 'Here', 'The', 'This', 'Note:')):
                continue
            # If line contains def, class, import, etc., start code block
            if stripped.startswith(('def ', 'class ', 'import ', 'from ', 'if __name__')):
                in_code_block = True
                code_lines.append(line)
            elif in_code_block:
                # If line has indentation or is empty, continue code block
                if line.startswith((' ', '\t')) or stripped == '':
                    code_lines.append(line)
                # If encountering obvious text line, end code block
                elif stripped and not any(keyword in stripped for keyword in ['#', 'return', 'if', 'for', 'while', 'try', 'except', 'with', 'assert', '=', 'print']):
                    if len(code_lines) > 3:  # At least some code
                        break
                    code_lines = []
                    in_code_block = False
                else:
                    code_lines.append(line)
        
        if code_lines:
            return '\n'.join(code_lines).strip()
    
    # If nothing found, return original text (might already be code)
    return text.strip()


def extract_completion_from_camel_result(camel_result: dict) -> str:
    """
    Extract code completion from CAMEL framework result.
    
    SRDD requires complete software code (including all functions, classes, imports, etc.),
    not just function body like HumanEval.
    
    Args:
        camel_result: CAMEL framework invoke result.
    
    Returns:
        Extracted complete code string.
    """
    conversation_result = camel_result.get("conversation_result", {})
    
    # Prioritize extracting from final assistant message
    final_assistant_message = conversation_result.get("final_assistant_message", "")
    if final_assistant_message:
        code = extract_python_code(final_assistant_message)
        if code:
            return code
    
    # If final message has no code, search in conversation history
    conversation_history = conversation_result.get("conversation_history", [])
    for msg in reversed(conversation_history):  # Search from back to front
        if msg.get("role") == "AI Assistant":
            content = msg.get("content", "")
            if content:
                code = extract_python_code(content)
                if code:
                    return code
    
    # If nothing found, return empty string
    return ""

