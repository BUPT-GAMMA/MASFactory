"""Extract Python code from CAMEL framework output - BigCodeBench version.

BigCodeBench requires complete code (including function signatures and import statements),
unlike HumanEval which only needs the function body.
"""

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
        entry_point: Function entry point name (optional, used to locate target function).
    
    Returns:
        Extracted Python code string (containing complete function definition).
    """
    if not text:
        return ""
    
    text = text.strip()
    
    # Filter out obvious explanatory text (non-model factor fix)
    # These texts usually appear before or after code
    explanation_patterns = [
        r'^The task is already complete.*?\n',
        r'^The function you provided.*?\n',
        r'^If you have any new requests.*?\n',
        r'^Next request.*?\n',
        r'^please let me know.*?\n',
        r'^If you require.*?\n',
        r'^Here is.*?\n',
        r'^This function.*?\n',
        r'^The solution.*?\n',
    ]
    
    for pattern in explanation_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)
    
    # Remove lines containing explanatory text (improved: also handle explanatory text in function body)
    lines = text.split('\n')
    filtered_lines = []
    skip_until_code = False
    in_function_body = False
    function_indent = 0
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip())
        
        # Detect if entering function body
        if stripped.startswith('def ') and current_indent == 0:
            in_function_body = True
            function_indent = current_indent
            filtered_lines.append(line)
            continue
        elif in_function_body:
            # In function body, check indentation
            if stripped and current_indent <= function_indent and not stripped.startswith(('def ', 'class ')):
                # Function body ended
                in_function_body = False
        
        # Skip obvious explanatory text lines (whether inside or outside function body)
        if any(phrase in stripped for phrase in [
            'The task is already complete',
            'The function you provided',
            'If you have any new requests',
            'Next request',
            'please let me know',
            'If you require',
            'Here is the',
            'This function',
            'The solution',
        ]):
            # If in function body, skip this line but maintain function body state
            if not in_function_body:
                skip_until_code = True
            continue
        
        # If encountering code lines (import, def, class, etc.), stop skipping
        if skip_until_code and stripped.startswith(('import ', 'from ', 'def ', 'class ')):
            skip_until_code = False
        
        if not skip_until_code:
            filtered_lines.append(line)
    
    text = '\n'.join(filtered_lines).strip()
    
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
                                        # May be function end
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
        # If entry_point is specified, prioritize exact match
        if entry_point:
            pattern = rf'(def\s+{re.escape(entry_point)}\s*\([^)]*\):.*?)(?=\n\ndef\s+|\nclass\s+|$)'
            match = re.search(pattern, text, re.DOTALL)
            if match:
                code = match.group(1).strip()
                if code:
                    return code
        
        # If entry_point is not specified or exact match failed, prioritize finding top-level functions
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
        
        # Skip obvious non-code lines (improved filtering logic)
        if any(phrase in stripped for phrase in [
            'Solution:', 'Instruction:', 'Input:', 
            'The task is already complete',
            'The function you provided',
            'If you have any new requests',
            'Next request',
            'please let me know',
            'If you require',
            'Here is the',
            'This function',
            'The solution',
        ]):
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
            elif stripped and not any(keyword in stripped for keyword in ['#', 'return', 'if', 'for', 'while', 'try', 'except', 'with', 'assert', 'def', 'class', 'import', 'from']):
                # Check if it's explanatory text
                if any(phrase in stripped for phrase in [
                    'The task', 'The function', 'If you', 'Next request',
                    'please let me know', 'Here is', 'This function'
                ]):
                    if len(code_lines) > 3:  # At least some code
                        break
                    code_lines = []
                    in_code_block = False
                else:
                    code_lines.append(line)
            else:
                code_lines.append(line)
    
    if code_lines:
        return '\n'.join(code_lines).strip()
    
    # Finally, if still not found, return original text (might already be code)
    return text.strip()


def extract_complete_solution_from_camel_result(
    camel_result: dict,
    code_prompt: str,
    entry_point: Optional[str] = None
) -> str:
    """
    Extract complete solution (including function signature) from CAMEL framework result.
    
    BigCodeBench requires complete code, including:
    - Import statements (if any)
    - Function signature (obtained from code_prompt)
    - Function body (extracted from CAMEL result)
    
    Args:
        camel_result: CAMEL framework invoke result
        code_prompt: BigCodeBench code_prompt (contains function signature)
        entry_point: Function entry point name (optional)
    
    Returns:
        Complete code string (including imports, function signature, and function body)
    """
    conversation_result = camel_result.get("conversation_result", {})
    
    # Extract import statements (from code_prompt)
    imports = []
    for line in code_prompt.split('\n'):
        stripped = line.strip()
        if stripped.startswith(('import ', 'from ')):
            imports.append(stripped)
    import_str = '\n'.join(imports) if imports else ""
    
    # Extract function signature (from code_prompt)
    # code_prompt usually ends with function signature, e.g.: def task_func(...):
    function_signature = None
    if entry_point:
        # Try to extract function signature from code_prompt
        pattern = rf'def\s+{re.escape(entry_point)}\s*\([^)]*\)\s*:'
        match = re.search(pattern, code_prompt)
        if match:
            function_signature = match.group(0).strip()
    
    if not function_signature:
        # If not found, try to extract from last few lines of code_prompt
        lines = code_prompt.strip().split('\n')
        for line in reversed(lines):
            stripped = line.strip()
            if stripped.startswith('def '):
                function_signature = stripped
                break
    
    # Prioritize extracting code from final assistant message
    final_assistant_message = conversation_result.get("final_assistant_message", "")
    extracted_code = ""
    is_complete_function = False
    
    if final_assistant_message:
        code = extract_python_code(final_assistant_message, entry_point)
        if code:
            # Check if it's a complete function definition (contains def line without indentation)
            first_line = code.split('\n')[0] if code else ""
            if first_line.strip().startswith('def ') and not first_line.startswith(' '):
                # This is a complete function definition, check if it contains imports
                is_complete_function = True
                extracted_code = code
            else:
                # This is function body, need to extract
                function_body = extract_function_body(code, entry_point)
                if function_body:
                    extracted_code = function_body
    
    # If final message has no code, search in conversation history
    if not extracted_code:
        conversation_history = conversation_result.get("conversation_history", [])
        for msg in reversed(conversation_history):  # Search from back to front
            if msg.get("role") == "AI Assistant":
                content = msg.get("content", "")
                if content:
                    code = extract_python_code(content, entry_point)
                    if code:
                        # Check if it's a complete function definition
                        first_line = code.split('\n')[0] if code else ""
                        if first_line.strip().startswith('def ') and not first_line.startswith(' '):
                            is_complete_function = True
                            extracted_code = code
                            break
                        else:
                            function_body = extract_function_body(code, entry_point)
                            if function_body:
                                extracted_code = function_body
                                break
    
    # Build complete code
    code_parts = []
    
    if is_complete_function and extracted_code:
        # If extracted is complete function definition, need to separate imports and function
        code_lines = extracted_code.split('\n')
        extracted_imports = []
        function_code_lines = []
        in_function = False
        
        for line in code_lines:
            stripped = line.strip()
            if stripped.startswith(('import ', 'from ')):
                extracted_imports.append(stripped)
            elif stripped.startswith('def ') and not line.startswith(' '):
                in_function = True
                function_code_lines.append(line)
            elif in_function:
                function_code_lines.append(line)
        
        # Merge imports (prioritize imports from code_prompt to avoid duplicates)
        all_imports = set()
        if import_str:
            for imp in import_str.split('\n'):
                if imp.strip():
                    all_imports.add(imp.strip())
        for imp in extracted_imports:
            if imp.strip():
                all_imports.add(imp.strip())
        
        if all_imports:
            code_parts.append('\n'.join(sorted(all_imports)))
        
        if function_code_lines:
            code_parts.append('\n'.join(function_code_lines))
    elif function_signature and extracted_code:
        # If extracted is function body, need to add function signature
        if import_str:
            code_parts.append(import_str)
        
        code_parts.append(function_signature)
        
        # Ensure function body has correct indentation (4 spaces) - use AST to help fix nested function indentation issues
        body_lines = extracted_code.split('\n')
        if not body_lines or not any(l.strip() for l in body_lines):
            code_parts.append('    pass')
        else:
            # Try to use AST to understand code structure
            import ast
            try:
                # Try to parse code to understand structure
                test_code = function_signature + "\n" + extracted_code
                tree = ast.parse(test_code)
                
                # If AST parsing succeeds, use AST information to fix indentation
                # Find all function definitions
                def_nodes = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        def_nodes.append(node)
                
                # If there are nested functions, need special handling
                if len(def_nodes) > 1:
                    # Has nested functions, need to fix indentation
                    fixed_lines = []
                    base_indent = 4
                    
                    # Re-analyze each line, fix indentation based on context
                    in_nested_function = False
                    nested_start = -1
                    nested_indent = 8
                    
                    for i, line in enumerate(body_lines):
                        stripped = line.strip()
                        if not stripped:
                            fixed_lines.append('')
                            continue
                        
                        current_indent = len(line) - len(line.lstrip())
                        
                        # Check if it's a nested function definition
                        if stripped.startswith('def ') and current_indent == 0:
                            # This should be a nested function, but indentation is 0, need to fix
                            fixed_lines.append(' ' * base_indent + stripped)
                            in_nested_function = True
                            nested_start = i
                            nested_indent = base_indent + 4
                        elif stripped.startswith('def ') and current_indent > 0:
                            # This is a nested function, indentation is correct
                            fixed_lines.append(line)
                            in_nested_function = True
                            nested_start = i
                            nested_indent = current_indent
                        elif in_nested_function:
                            # Inside nested function
                            if current_indent > nested_indent:
                                # Nested function body
                                fixed_lines.append(line)
                            elif current_indent == nested_indent or current_indent < nested_indent:
                                # Nested function ends, return to outer function body
                                in_nested_function = False
                                # This should be outer function body, indentation should be base_indent
                                if current_indent >= nested_indent:
                                    fixed_lines.append(' ' * base_indent + stripped)
                                else:
                                    fixed_lines.append(line)
                            else:
                                fixed_lines.append(line)
                        else:
                            # Outer function body
                            if current_indent == 0 and stripped.startswith(('def ', 'class ')):
                                # This should be a nested function, but indentation is 0
                                fixed_lines.append(' ' * base_indent + stripped)
                            elif current_indent < base_indent:
                                # Indentation too small, should be base_indent
                                fixed_lines.append(' ' * base_indent + stripped)
                            else:
                                fixed_lines.append(line)
                    
                    indented_body = fixed_lines
                else:
                    # No nested functions, use original logic
                    raise ValueError("No nested functions")
                    
            except (SyntaxError, ValueError, AttributeError):
                # AST parsing failed, use improved heuristic method
                # Intelligently detect function body indentation level (fix nested function indentation issues)
                indent_levels = []
                def_positions = []  # Record position and indentation of all def statements
                
                for i, line in enumerate(body_lines):
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        current_indent = len(line) - len(line.lstrip())
                        if current_indent not in indent_levels:
                            indent_levels.append(current_indent)
                        if stripped.startswith('def '):
                            def_positions.append((i, current_indent))
                
                indent_levels.sort()
                
                # Determine base indentation for function body
                if not indent_levels:
                    min_indent = 4
                else:
                    # Count usage frequency of each indentation level (excluding def lines)
                    indent_counts = {}
                    for line in body_lines:
                        stripped = line.strip()
                        if stripped and not stripped.startswith('#') and not stripped.startswith('def '):
                            current_indent = len(line) - len(line.lstrip())
                            indent_counts[current_indent] = indent_counts.get(current_indent, 0) + 1
                    
                    # Find most common indentation level
                    if indent_counts:
                        # Prioritize indentation that is multiple of 4 and most common
                        candidate_indents = [ind for ind in indent_levels if ind >= 4 and ind % 4 == 0]
                        if candidate_indents:
                            min_indent = max(candidate_indents, key=lambda x: indent_counts.get(x, 0))
                        else:
                            min_indent = min([ind for ind in indent_levels if ind >= 4], default=4)
                    else:
                        min_indent = indent_levels[0] if indent_levels[0] >= 4 else 4
                    
                    if min_indent < 4:
                        min_indent = 4
            
            # Normalize indentation: intelligently handle nested function structure (improved version)
            indented_body = []
            base_indent = 4  # Base indentation for function body
            
            # Step 1: Fix obvious indentation errors (def statements with indentation 0 in function body should be nested functions)
            fixed_lines = []
            for i, line in enumerate(body_lines):
                stripped = line.strip()
                if stripped.startswith('def ') and i > 0:
                    # Check if previous line has indentation (indicates inside function body)
                    prev_line = body_lines[i-1] if i > 0 else ""
                    if prev_line.strip() and len(prev_line) - len(prev_line.lstrip()) > 0:
                        # Previous line has indentation, indicates inside function body, this should be a nested function
                        current_indent = len(line) - len(line.lstrip())
                        if current_indent == 0:
                            # Indentation is 0, should be nested function, fix to 4 spaces
                            fixed_lines.append(' ' * base_indent + stripped)
                            continue
                fixed_lines.append(line)
            
            body_lines = fixed_lines
            
            # Step 2: Detect nested function structure
            nested_functions = []  # [(start_line, end_line, indent)]
            current_nested = None
            
            for i, line in enumerate(body_lines):
                stripped = line.strip()
                if stripped.startswith('def '):
                    current_indent = len(line) - len(line.lstrip())
                    if current_indent >= base_indent:  # This is a nested function (indentation >= 4)
                        if current_nested is None:
                            current_nested = (i, current_indent)
                    else:
                        # Top-level function, end previous nested function
                        if current_nested:
                            nested_functions.append((current_nested[0], i, current_nested[1]))
                            current_nested = None
                elif current_nested and stripped:
                    # Check if still inside nested function
                    current_indent = len(line) - len(line.lstrip())
                    if current_indent <= current_nested[1] and not stripped.startswith('def '):
                        # Nested function ends (indentation returns to nested function definition level or less)
                        nested_functions.append((current_nested[0], i, current_nested[1]))
                        current_nested = None
            
            if current_nested:
                nested_functions.append((current_nested[0], len(body_lines), current_nested[1]))
            
            # Step 3: Normalize indentation
            for i, line in enumerate(body_lines):
                stripped = line.strip()
                if not stripped:
                    indented_body.append('')
                elif stripped.startswith('#'):
                    # Comment lines maintain relative position
                    original_indent = len(line) - len(line.lstrip())
                    relative_indent = original_indent - min_indent
                    new_indent = base_indent + relative_indent
                    if new_indent < base_indent:
                        new_indent = base_indent
                    indented_body.append(' ' * new_indent + stripped)
                else:
                    original_indent = len(line) - len(line.lstrip())
                    
                    # Check if inside nested function
                    in_nested = False
                    nested_end = -1
                    for start, end, nested_indent in nested_functions:
                        if start <= i < end:
                            in_nested = True
                            nested_end = max(nested_end, end)
                            break
                    
                    # Special handling: fix indentation errors
                    if not in_nested:
                        # Not inside nested function
                        if stripped.startswith('def ') and original_indent == 0:
                            # def with indentation 0, should be nested function
                            new_indent = base_indent
                        elif original_indent == min_indent and min_indent > base_indent:
                            # Indentation equals min_indent but not in nested function, should be function body level
                            new_indent = base_indent
                        elif i > nested_end and original_indent >= min_indent + 4:
                            # After nested function, and indentation >= nested function body, should be function body level
                            new_indent = base_indent
                        else:
                            # Normal relative indentation calculation
                            relative_indent = original_indent - min_indent
                            new_indent = base_indent + relative_indent
                    else:
                        # Inside nested function, normal relative indentation calculation
                        relative_indent = original_indent - min_indent
                        new_indent = base_indent + relative_indent
                    
                    # Ensure at least 4 spaces
                    if new_indent < base_indent:
                        new_indent = base_indent
                    # Align to multiple of 4 (Python standard)
                    if new_indent % 4 != 0:
                        new_indent = ((new_indent // 4) + 1) * 4
                    indented_body.append(' ' * new_indent + stripped)
            
            code_parts.append('\n'.join(indented_body))
    elif extracted_code:
        # If only code but no function signature, use directly (might be complete code)
        code_parts.append(extracted_code)
    else:
        # If nothing, at least return function signature and pass
        if import_str:
            code_parts.append(import_str)
        if function_signature:
            code_parts.append(function_signature)
            code_parts.append('    pass')
    
    return '\n'.join(code_parts)


def extract_function_body(code: str, entry_point: Optional[str] = None) -> str:
    """
    Extract function body part from code containing function definition.
    
    Args:
        code: Code containing function definition
        entry_point: Function name (optional)
    
    Returns:
        Function body code (with indentation, excluding def line)
    """
    if not code or not code.strip():
        return ""
    
    lines = code.split('\n')
    function_start = None
    function_indent = None
    
    # Find function definition line
    if entry_point:
        # Exact match entry_point function
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f'def {entry_point}'):
                match = re.match(rf'def\s+{re.escape(entry_point)}\s*\(', stripped)
                if match:
                    function_start = i
                    function_indent = len(line) - len(line.lstrip())
                    break
    else:
        # If entry_point not specified, prioritize finding top-level function (indentation 0)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('def '):
                indent = len(line) - len(line.lstrip())
                if indent == 0:
                    function_start = i
                    function_indent = indent
                    break
        
        # If no top-level function, use first function
        if function_start is None:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('def '):
                    function_start = i
                    function_indent = len(line) - len(line.lstrip())
                    break
    
    if function_start is None:
        # If function definition not found, might be pure function body, return directly
        return code.strip()
    
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
    
    result = '\n'.join(body_lines).strip() if body_lines else ""
    return result
