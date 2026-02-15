"""Extract Python code from CAMEL framework output."""

import re
from typing import Optional


def extract_python_code(text: str, entry_point: Optional[str] = None) -> str:
    """
    Extract Python code from text.
    
    Priority extraction:
    1. Code block containing entry_point function
    2. Python code in markdown code blocks
    3. Directly included Python code
    
    Args:
        text: Text containing code.
        entry_point: Function entry point name (optional, for locating target function).
    
    Returns:
        Extracted Python code string.
    """
    if not text:
        return ""
    
    text = text.strip()
    
    # If entry_point exists, try to extract code containing that function
    if entry_point:
        # Try to match code block containing entry_point
        pattern = rf'(def\s+{re.escape(entry_point)}\s*\([^)]*\):.*?)(?=\n\ndef\s+|\nclass\s+|$)'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            code = match.group(1).strip()
            # Ensure complete function body is included
            if code.count('def') == 1:
                # Try to find function end position (next def or class or end of file)
                lines = text.split('\n')
                start_idx = text.find(code)
                if start_idx != -1:
                    start_line = text[:start_idx].count('\n')
                    # Find function definition line
                    for i, line in enumerate(lines[start_line:], start_line):
                        if line.strip().startswith(f'def {entry_point}'):
                            # Found function definition, extract to next def/class or end of file
                            code_lines = []
                            indent_level = None
                            for j in range(i, len(lines)):
                                current_line = lines[j]
                                if j == i:
                                    code_lines.append(current_line)
                                    # Determine function body indentation level
                                    if ':' in current_line:
                                        indent_level = len(current_line) - len(current_line.lstrip()) + 4
                                elif indent_level is not None:
                                    # Check if it's part of function body
                                    if current_line.strip() == '':
                                        code_lines.append(current_line)
                                    elif current_line.strip().startswith('#'):
                                        code_lines.append(current_line)
                                    elif len(current_line) - len(current_line.lstrip()) >= indent_level:
                                        code_lines.append(current_line)
                                    elif current_line.strip().startswith(('def ', 'class ')):
                                        break
                                    else:
                                        # Might be function end
                                        break
                            return '\n'.join(code_lines)
    
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
    
    # Try to extract direct function definition (if contains def keyword)
    if 'def ' in text:
        # If entry_point specified, prioritize exact match
        if entry_point:
            pattern = rf'(def\s+{re.escape(entry_point)}\s*\([^)]*\):.*?)(?=\n\ndef\s+|\nclass\s+|$)'
            match = re.search(pattern, text, re.DOTALL)
            if match:
                code = match.group(1).strip()
                if code:
                    return code
        
        # If entry_point not specified or exact match failed, prioritize finding top-level functions
        lines = text.split('\n')
        top_level_functions = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('def '):
                indent = len(line) - len(line.lstrip())
                if indent == 0:
                    # This is a top-level function
                    match = re.match(r'def\s+(\w+)\s*\(', stripped)
                    if match:
                        top_level_functions.append((i, match.group(1)))
        
        if top_level_functions:
            # Use first top-level function
            start_idx, func_name = top_level_functions[0]
            # Extract content from this function to next top-level function/class
            code_lines = []
            for i in range(start_idx, len(lines)):
                line = lines[i]
                if i == start_idx:
                    code_lines.append(line)
                elif i > start_idx:
                    stripped = line.strip()
                    # If encountering next top-level function/class, stop
                    if stripped.startswith(('def ', 'class ')):
                        indent = len(line) - len(line.lstrip())
                        if indent == 0:
                            break
                    code_lines.append(line)
            code = '\n'.join(code_lines).strip()
            if code:
                return code
        
        # If no top-level functions, use first function
        def_pattern = r'(def\s+\w+\s*\([^)]*\):.*?)(?=\n\ndef\s+|\nclass\s+|$)'
        match = re.search(def_pattern, text, re.DOTALL)
        if match:
            code = match.group(1).strip()
            if code:
                return code
    
    # If nothing found, try to extract parts that look like code
    # Find code blocks with indentation
    lines = text.split('\n')
    code_lines = []
    in_code_block = False
    
    for line in lines:
        stripped = line.strip()
        # Skip obvious non-code lines
        if stripped.startswith(('Solution:', 'Instruction:', 'Input:', 'Here', 'The', 'This')):
            continue
        # If line contains def or class, start code block
        if stripped.startswith(('def ', 'class ', 'import ', 'from ')):
            in_code_block = True
            code_lines.append(line)
        elif in_code_block:
            # If line has indentation or is empty, continue code block
            if line.startswith((' ', '\t')) or stripped == '':
                code_lines.append(line)
            # If encountering obvious text line, end code block
            elif stripped and not any(keyword in stripped for keyword in ['#', 'return', 'if', 'for', 'while', 'try', 'except', 'with', 'assert']):
                if len(code_lines) > 3:  # At least some code
                    break
                code_lines = []
                in_code_block = False
            else:
                code_lines.append(line)
    
    if code_lines:
        return '\n'.join(code_lines).strip()
    
    # Finally, if still not found, return original text (might already be code)
    return text.strip()


def extract_function_body_only(code: str, entry_point: Optional[str] = None) -> str:
    """
    Extract function body part from code containing function definition (for HumanEval).
    
    HumanEval needs function body, not including function signature.
    
    Args:
        code: Code containing function definition.
        entry_point: Function name (optional).
    
    Returns:
        Function body code (with indentation, excluding def line).
    """
    if not code or not code.strip():
        return ""
    
    lines = code.split('\n')
    function_start = None
    function_indent = None
    
    # Find function definition line
    # If entry_point specified, prioritize exact match
    # If entry_point not specified, prioritize finding top-level functions (functions with indentation 0)
    if entry_point:
        # Exact match entry_point function
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f'def {entry_point}'):
                # Check if function name matches exactly (avoid partial match)
                match = re.match(rf'def\s+{re.escape(entry_point)}\s*\(', stripped)
                if match:
                    function_start = i
                    function_indent = len(line) - len(line.lstrip())
                    break
    else:
        # Entry_point not specified, prioritize finding top-level functions (indentation 0)
        # First find all top-level functions
        top_level_functions = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('def '):
                indent = len(line) - len(line.lstrip())
                if indent == 0:
                    # This is a top-level function
                    match = re.match(r'def\s+(\w+)\s*\(', stripped)
                    if match:
                        top_level_functions.append((i, indent, match.group(1)))
        
        if top_level_functions:
            # Use first top-level function
            function_start, function_indent, _ = top_level_functions[0]
        else:
            # If no top-level functions, use first function (might be nested function)
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('def '):
                    function_start = i
                    function_indent = len(line) - len(line.lstrip())
                    break
    
    if function_start is None:
        # If function definition not found, might be pure function body, need to normalize indentation
        result = code.strip()
    else:
        # Extract function body (starting from first line after function definition)
        body_lines = []
        expected_indent = function_indent + 4  # Function body should have 4-space indentation
        
        for i in range(function_start + 1, len(lines)):
            line = lines[i]
            stripped = line.strip()
            
            if not stripped:
                # Preserve empty lines
                body_lines.append(line)
                continue
            
            current_indent = len(line) - len(line.lstrip())
            
            # If encountering next top-level function or class definition (same level or less indentation), stop
            # But if it's a nested function (indentation greater than function_indent), should be included in function body
            if stripped.startswith(('def ', 'class ')):
                if current_indent <= function_indent:
                    # This is another top-level function/class, stop
                    break
                else:
                    # This is a nested function, should be included in function body
                    body_lines.append(line)
                    continue
            
            # Check if it's part of function body
            if current_indent > function_indent:
                # Has indentation, is part of function body (including nested functions)
                body_lines.append(line)
            elif current_indent == function_indent and stripped.startswith('#'):
                # Same-level comment, might be part of function body
                body_lines.append(line)
            else:
                # Function body ends
                break
        
        # Remove trailing empty lines and comments
        while body_lines:
            last_line = body_lines[-1].strip()
            if not last_line or last_line.startswith('#'):
                body_lines.pop()
            else:
                break
        
        # Extract function body from function definition
        result = '\n'.join(body_lines).strip() if body_lines else ""
        if not result:
            result = code.strip()
    
    # Clean and normalize indentation: ensure all code lines have 4-space indentation
    # First remove docstring (HumanEval doesn't need docstring)
    lines = result.split('\n')
    filtered_lines = []
    in_docstring = False
    docstring_delimiter = None
    
    for line in lines:
        stripped = line.strip()
        
        # Detect docstring start and end
        if '"""' in stripped or "'''" in stripped:
            # Check if it's start or end
            quote_count = stripped.count('"""') + stripped.count("'''")
            if quote_count % 2 == 1:  # Odd number of quotes, indicates start or end
                if not in_docstring:
                    # Start docstring
                    in_docstring = True
                    if '"""' in stripped:
                        docstring_delimiter = '"""'
                    else:
                        docstring_delimiter = "'''"
                    # Skip this line
                    continue
                else:
                    # End docstring
                    if (docstring_delimiter == '"""' and '"""' in stripped) or \
                       (docstring_delimiter == "'''" and "'''" in stripped):
                        in_docstring = False
                        docstring_delimiter = None
                        # Skip this line
                        continue
        
        # If in docstring, skip this line
        if in_docstring:
            continue
        
        # Keep non-docstring lines
        filtered_lines.append(line)
    
    result = '\n'.join(filtered_lines)
    
    cleaned_lines = []
    min_indent = None
    
    # First find minimum indentation (for normalization)
    for line in result.split('\n'):
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            current_indent = len(line) - len(line.lstrip())
            if min_indent is None or current_indent < min_indent:
                min_indent = current_indent
    
    # HumanEval expects 4-space indentation
    target_indent = 4
    
    # Identify all nested function definition positions and indentation
    lines = result.split('\n')
    nested_functions = []  # (line_index, def_indent)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('def '):
            indent = len(line) - len(line.lstrip())
            if indent > 0:  # Nested function (has indentation)
                nested_functions.append((i, indent))
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            # Preserve empty lines
            cleaned_lines.append(line)
            continue
        
        # Skip unindented comment lines (these might be explanatory text, not code)
        if stripped.startswith('#') and not line.startswith(' '):
            continue
        
        current_indent = len(line) - len(line.lstrip())
        
        # Check if this line is inside a nested function body
        # Find closest nested function definition (before current line, and indentation less than current line)
        in_nested_function = False
        nested_def_indent = None
        closest_nested_def = None
        closest_def_indent = None
        
        for def_idx, def_indent in nested_functions:
            if i > def_idx:  # After def line
                # Check if still in this function body (indentation greater than def_indent)
                if current_indent > def_indent:
                    # Check if it's next same-level or higher-level def
                    is_next_def = False
                    for next_def_idx, next_def_indent in nested_functions:
                        if next_def_idx > def_idx and i >= next_def_idx:
                            if next_def_indent <= def_indent:
                                is_next_def = True
                                break
                    if not is_next_def:
                        # This is the closest nested function
                        if closest_nested_def is None or def_idx > closest_nested_def:
                            closest_nested_def = def_idx
                            closest_def_indent = def_indent
                            in_nested_function = True
                            nested_def_indent = def_indent
        
        # If nested function found, use closest one
        if in_nested_function and closest_def_indent is not None:
            nested_def_indent = closest_def_indent
        
        # Normalize indentation
        if current_indent == 0:
            # If completely no indentation, add 4 spaces
            cleaned_lines.append(' ' * target_indent + stripped)
        elif current_indent < target_indent:
            # If indentation insufficient, adjust to 4 spaces
            cleaned_lines.append(' ' * target_indent + stripped)
        elif in_nested_function and nested_def_indent is not None:
            # Inside nested function body, need to ensure indentation is correct
            # Nested function body should have nested_def_indent + 4 indentation
            expected_indent = nested_def_indent + 4
            if current_indent == expected_indent:
                # Indentation correct, use directly
                cleaned_lines.append(line)
            elif current_indent > expected_indent:
                # Indentation too much, might be nested nested function or code block
                # Maintain relative indentation, but ensure at least expected_indent
                # If indentation is multiple of expected_indent + 4, maintain relative indentation
                if (current_indent - expected_indent) % 4 == 0:
                    # Relative indentation is multiple of 4, maintain
                    cleaned_lines.append(line)
                else:
                    # Relative indentation not multiple of 4, adjust to nearest multiple of 4
                    relative_indent = current_indent - expected_indent
                    adjusted_relative = ((relative_indent + 2) // 4) * 4  # Round to nearest multiple of 4
                    new_indent = expected_indent + adjusted_relative
                    cleaned_lines.append(' ' * new_indent + stripped)
            else:
                # Indentation insufficient, adjust to expected_indent
                cleaned_lines.append(' ' * expected_indent + stripped)
        elif current_indent > target_indent:
            # Not in nested function body, but indentation greater than 4
            # Maintain relative indentation but adjust base indentation
            if min_indent is not None and min_indent > 0:
                # Calculate relative indentation (relative to minimum indentation)
                relative_indent = current_indent - min_indent
                # New indentation = target indentation + relative indentation
                new_indent = target_indent + relative_indent
                cleaned_lines.append(' ' * new_indent + stripped)
            else:
                # If cannot determine minimum indentation, keep as is
                cleaned_lines.append(line)
        else:
            # Indentation correct (4 spaces), use directly
            cleaned_lines.append(line)
    
    # Don't use .strip(), as it will remove indentation from first line!
    # Only remove trailing empty lines
    result_lines = cleaned_lines
    while result_lines and not result_lines[-1].strip():
        result_lines.pop()
    return '\n'.join(result_lines)


def extract_completion_from_camel_result(
    camel_result: dict,
    entry_point: Optional[str] = None
) -> str:
    """
    Extract code completion from CAMEL framework result.
    
    HumanEval needs function body (not including function signature), because prompt already contains function signature.
    Function body should include all nested helper function definitions.
    
    Args:
        camel_result: CAMEL framework invoke result.
        entry_point: Function entry point name (optional).
    
    Returns:
        Extracted function body code string (not including function signature, but including nested functions).
    """
    conversation_result = camel_result.get("conversation_result", {})
    
    # Prioritize extracting from final assistant message
    final_assistant_message = conversation_result.get("final_assistant_message", "")
    if final_assistant_message:
        code = extract_python_code(final_assistant_message, entry_point)
        if code:
            # Extract function body (remove function signature, but keep nested functions)
            body = extract_function_body_only(code, entry_point)
            if body:
                # Ensure function body includes all nested function definitions
                # extract_function_body_only should have already handled nested functions
                return body
    
    # If final message has no code, search in conversation history
    conversation_history = conversation_result.get("conversation_history", [])
    for msg in reversed(conversation_history):  # Search from back to front
        if msg.get("role") == "AI Assistant":
            content = msg.get("content", "")
            if content:
                code = extract_python_code(content, entry_point)
                if code:
                    # Extract function body (remove function signature, but keep nested functions)
                    body = extract_function_body_only(code, entry_point)
                    if body:
                        return body
    
    # If nothing found, return empty string
    return ""

