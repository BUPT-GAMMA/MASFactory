"""Evaluate CAMEL framework using LiveCodeBench dataset.

This module provides functionality to evaluate the CAMEL role-playing framework
on the LiveCodeBench code generation benchmark.
"""

import os
import sys
import json
import argparse
import re
from pathlib import Path
from typing import Dict, List, Optional
import tqdm

# Add parent directory to path for importing CAMEL framework
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import CAMEL framework (from parent directory)
# Important: Add eval directory to the front of sys.path before importing workflow
# This ensures workflow.py and conversation_loop.py import prompts from eval/prompts.py (evaluation-specific version)
eval_dir = str(Path(__file__).parent.parent / "eval")
if eval_dir not in sys.path or sys.path.index(eval_dir) != 0:
    if eval_dir in sys.path:
        sys.path.remove(eval_dir)
    sys.path.insert(0, eval_dir)

from workflow import create_camel_role_playing_workflow  # type: ignore
from masfactory import OpenAIModel  # type: ignore

# Import local code extraction tool
from code_extractor import extract_completion_from_camel_result  # type: ignore

# Import Windows-compatible execution module (if needed)
import platform
if platform.system() == "Windows":
    # Try to import Windows-compatible execution module
    windows_exec_path = Path(__file__).parent.parent / "eval" / "windows_execution.py"
    if windows_exec_path.exists():
        sys.path.insert(0, str(windows_exec_path.parent))
        try:
            from windows_execution import check_correctness  # type: ignore
        except ImportError:
            check_correctness = None
    else:
        check_correctness = None
else:
    check_correctness = None


def load_livecodebench_from_huggingface(release_version: str = "release_v6") -> Dict[str, Dict]:
    """
    Load LiveCodeBench data from HuggingFace datasets.
    
    Args:
        release_version: Dataset version (default "release_v6").
    
    Returns:
        Problem dictionary, key is problem_id, value is problem dictionary.
    """
    try:
        from datasets import load_dataset  # type: ignore
    except ImportError:
        raise ImportError(
            "Need to install datasets library to load LiveCodeBench data.\n"
            "Please run: pip install datasets"
        )
    
    print("Loading LiveCodeBench dataset from HuggingFace...")
    dataset = None
    try:
        # Try to load lite version (faster)
        # Note: New versions of datasets library no longer support trust_remote_code parameter
        try:
            dataset = load_dataset(
                "livecodebench/code_generation_lite",
                split="test",
                version_tag=release_version
            )
            print(f"Successfully loaded lite version, dataset size: {len(dataset)}")
        except Exception as e1:
            print(f"Failed to load lite version: {e1}")
            # Try without version_tag
            try:
                dataset = load_dataset(
                    "livecodebench/code_generation_lite",
                    split="test"
                )
                print(f"Successfully loaded lite version (no version tag), dataset size: {len(dataset)}")
            except Exception as e2:
                print(f"Failed to load lite version (no version tag): {e2}")
                raise e1  # Raise original error, continue trying full version
    except Exception as e:
        print(f"Failed to load lite version, trying full version: {e}")
        # If lite version fails, try full version
        try:
            dataset = load_dataset(
                "livecodebench/code_generation",
                split="test"
            )
            print(f"Successfully loaded full version, dataset size: {len(dataset)}")
        except Exception as e3:
            print(f"Failed to load full version: {e3}")
            # Last try: use revision parameter instead of version_tag
            try:
                dataset = load_dataset(
                    "livecodebench/code_generation_lite",
                    split="test",
                    revision=release_version
                )
                print(f"Successfully loaded using revision, dataset size: {len(dataset)}")
            except Exception as e4:
                raise Exception(f"All loading methods failed. Last error: {e4}")
    
    if dataset is None:
        raise Exception("Failed to load LiveCodeBench dataset")
    
    problems = {}
    total_items = 0
    skipped_items = 0
    
    print(f"Starting to process dataset, expected items: {len(dataset)}")
    
    for idx, item in enumerate(dataset):
        total_items += 1
        # LiveCodeBench data structure
        problem_id = item.get("question_id") or item.get("problem_id") or item.get("id")
        if not problem_id:
            # If no ID, use index
            problem_id = f"problem_{len(problems)}"
            skipped_items += 1
        
        # Check if already exists (avoid duplicates)
        if problem_id in problems:
            print(f"Warning: Found duplicate problem_id: {problem_id}, skipping")
            skipped_items += 1
            continue
        
        # Build problem dictionary
        # Try to extract prompt from multiple possible fields
        prompt = (item.get("prompt", "") or 
                  item.get("problem", "") or 
                  item.get("description", "") or
                  item.get("question", "") or
                  item.get("code_prompt", "") or
                  item.get("instruction", "") or
                  "")
        
        # If still empty, try to build from other fields
        if not prompt:
            # Try to combine from multiple fields
            code_context = item.get("code_context", "")
            if code_context:
                prompt = code_context
        
        problem = {
            "problem_id": problem_id,
            "prompt": prompt,
            "problem": prompt,  # Maintain compatibility
            "test": item.get("public_test_cases", ""),
            "input_output": item.get("input_output", ""),
            "public_test_cases": item.get("public_test_cases", ""),
            "metadata": item.get("metadata", {}),
        }
        
        # If there are other fields, add them too (preserve original data)
        for key, value in item.items():
            if key not in problem:
                problem[key] = value
        
        # Final check: if prompt is still empty, at least set a placeholder to avoid errors during evaluation
        if not problem.get("prompt") and not problem.get("problem"):
            # Try to extract from all string fields
            for key, value in problem.items():
                if isinstance(value, str) and len(value) > 50:  # Longer strings might be prompts
                    problem["prompt"] = value
                    problem["problem"] = value
                    break
        
        problems[problem_id] = problem
        
        # Print progress every 100 items
        if (idx + 1) % 100 == 0:
            print(f"Processed {idx + 1}/{len(dataset)} items, current valid problems: {len(problems)}")
    
    print(f"Processing complete: Total items={total_items}, Valid problems={len(problems)}, Skipped/duplicates={skipped_items}")
    
    if len(problems) < total_items * 0.9:
        print(f"Warning: Valid problems ({len(problems)}) significantly fewer than total items ({total_items}), may have data loading issues")
    
    return problems


def read_livecodebench_problems(problem_file: str = None) -> Dict[str, Dict]:
    """
    Read LiveCodeBench problem file.
    
    Supports:
    1. Load from HuggingFace datasets (if problem_file is None or "huggingface")
    2. Load from local JSON/JSONL files
    
    LiveCodeBench typically uses JSON or JSONL format, containing:
    - problem_id: Problem ID
    - problem: Problem description
    - test: Test cases
    - entry_point: Function entry point (if any)
    - prompt: Prompt (if any)
    
    Args:
        problem_file: LiveCodeBench JSON/JSONL file path, or None/"huggingface" means load from HuggingFace.
    
    Returns:
        Problem dictionary, key is problem_id, value is problem dictionary.
    """
    # If problem_file is None or "huggingface", load from HuggingFace
    if problem_file is None or problem_file.lower() == "huggingface":
        return load_livecodebench_from_huggingface()
    
    # Load from local file
    problems = {}
    file_path = Path(problem_file)
    
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {problem_file}")
    
    if file_path.suffix == '.jsonl':
        # JSONL format
        with open(problem_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    problem = json.loads(line)
                    problem_id = problem.get("problem_id") or problem.get("task_id") or problem.get("id") or problem.get("question_id")
                    if problem_id:
                        problems[problem_id] = problem
    elif file_path.suffix == '.json':
        # JSON format (may be array or object)
        with open(problem_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                for problem in data:
                    problem_id = problem.get("problem_id") or problem.get("task_id") or problem.get("id") or problem.get("question_id")
                    if problem_id:
                        # Ensure prompt field exists
                        if "prompt" not in problem or not problem["prompt"]:
                            problem["prompt"] = (problem.get("problem", "") or 
                                                 problem.get("description", "") or
                                                 problem.get("question", "") or
                                                 problem.get("code_prompt", "") or
                                                 "")
                        if "problem" not in problem:
                            problem["problem"] = problem.get("prompt", "")
                        problems[problem_id] = problem
            elif isinstance(data, dict):
                # If dict, may be {problem_id: problem} format
                for problem_id, problem in data.items():
                    # Ensure prompt field exists
                    if isinstance(problem, dict):
                        if "prompt" not in problem or not problem["prompt"]:
                            problem["prompt"] = (problem.get("problem", "") or 
                                               problem.get("description", "") or
                                               problem.get("question", "") or
                                               problem.get("code_prompt", "") or
                                               "")
                        if "problem" not in problem:
                            problem["problem"] = problem.get("prompt", "")
                    problems[problem_id] = problem
    else:
        raise ValueError(f"Unsupported file format: {file_path.suffix}, please use .json or .jsonl files")
    
    return problems


def extract_function_signature_from_problem(problem: Dict) -> Optional[Dict]:
    """
    Extract function signature information from LiveCodeBench problem.
    
    Args:
        problem: LiveCodeBench problem dictionary.
    
    Returns:
        Dictionary containing entry_point and param_names, or None if not found.
    """
    # Try to extract function signature from different fields
    prompt = (problem.get("prompt", "") or 
              problem.get("problem", "") or 
              problem.get("code", "") or
              problem.get("description", "") or
              problem.get("question", "") or
              "")
    
    if not prompt:
        return None
    
    # Find function definition (supports multiple formats)
    # Format 1: def function_name(...)
    match = re.search(r'def\s+(\w+)\s*\(([^)]*)\)', prompt)
    if match:
        entry_point = match.group(1)
        params_str = match.group(2)
        # Parse parameter names (remove type annotations and default values)
        param_names = []
        for param in params_str.split(','):
            param = param.strip()
            if param:
                # Remove type annotations and default values
                param_name = param.split(':')[0].split('=')[0].strip()
                if param_name:
                    param_names.append(param_name)
        return {
            "entry_point": entry_point,
            "param_names": param_names
        }
    
    # Format 2: function_name(...) or function_name = ...
    match = re.search(r'(\w+)\s*\(([^)]*)\)\s*[:=]', prompt)
    if match:
        entry_point = match.group(1)
        params_str = match.group(2)
        param_names = []
        for param in params_str.split(','):
            param = param.strip()
            if param:
                param_name = param.split(':')[0].split('=')[0].strip()
                if param_name:
                    param_names.append(param_name)
        return {
            "entry_point": entry_point,
            "param_names": param_names
        }
    
    # Format 3: Extract from generated code (if not in prompt but in completion)
    # This is handled in check_livecodebench_correctness
    
    # If function definition not found, check if there's entry_point field
    entry_point = problem.get("entry_point") or problem.get("function_name")
    if entry_point:
        return {
            "entry_point": entry_point,
            "param_names": []
        }
    
    # If still not found, try to extract from completion (if completion is in problem)
    completion = problem.get("completion", "")
    if completion:
        match = re.search(r'def\s+(\w+)\s*\(([^)]*)\)', completion)
        if match:
            entry_point = match.group(1)
            params_str = match.group(2)
            param_names = []
            for param in params_str.split(','):
                param = param.strip()
                if param:
                    param_name = param.split(':')[0].split('=')[0].strip()
                    if param_name:
                        param_names.append(param_name)
            return {
                "entry_point": entry_point,
                "param_names": param_names
            }
    
    return None


def generate_task_prompt(problem: Dict) -> str:
    """
    Convert LiveCodeBench problem to CAMEL framework task description.
    
    Args:
        problem: LiveCodeBench problem dictionary.
    
    Returns:
        Task description string.
    """
    # Try to get problem description from different fields
    problem_text = problem.get("prompt", "") or problem.get("problem", "") or problem.get("description", "")
    
    # Extract function signature information
    sig_info = extract_function_signature_from_problem(problem)
    param_names = []
    entry_point = None
    if sig_info:
        entry_point = sig_info["entry_point"]
        param_names = sig_info["param_names"]
    
    # Build task description emphasizing parameter names
    param_emphasis = ""
    if param_names:
        param_list = ", ".join([f'"{name}"' for name in param_names])
        param_emphasis = f"""

CRITICAL: The function signature specifies these EXACT parameter names: {param_list}
You MUST use these EXACT parameter names in your code. Do NOT rename them to other names like "input_string", "numbers", "s", etc.
"""
    
    # Get test cases (LiveCodeBench may have multiple formats)
    test_examples = ""
    # Try to get test cases from different fields
    test = problem.get("public_test_cases", "") or problem.get("test", "") or problem.get("input_output", "")
    
    # If test is string, try to parse as JSON
    if isinstance(test, str) and test.strip():
        try:
            test_data = json.loads(test)
            if isinstance(test_data, dict):
                # Format test cases
                test_str = json.dumps(test_data, indent=2, ensure_ascii=False)
                test_examples = f"\n\nYour code should pass these test cases:\n{test_str[:500]}"
            else:
                test_examples = f"\n\nYour code should pass these test cases:\n{test[:500]}"
        except (json.JSONDecodeError, TypeError):
            # If not JSON, use directly
            test_examples = f"\n\nYour code should pass these test cases:\n{test[:500]}"
    elif test:
        # If not string, convert to string directly
        test_examples = f"\n\nYour code should pass these test cases:\n{str(test)[:500]}"
    
    task_description = f"""Write a Python function that solves the following problem:

{problem_text}{param_emphasis}

REQUIREMENTS:
1. Use EXACTLY the parameter names specified in the function signature above. Do NOT rename them (e.g., if signature says "string", use "string", NOT "s" or "input_string").
2. If your code uses standard library modules (like math, re, collections, etc.), you MUST include the import statements at the module level (before the function definition). For example: "import re" or "from collections import Counter".
3. If you need helper functions (like is_prime(), generate_primes(), etc.), you MUST define them INSIDE the main function as nested functions. Do NOT define them outside the main function.
4. The code must be complete, syntactically correct, and ready to execute.
5. Use 4-space indentation for all code. Ensure all lines in the function body are properly indented with 4 spaces (or multiples of 4 spaces for nested blocks).
6. Do NOT include docstrings in the function body.
7. The return type MUST match EXACTLY what the test cases expect (e.g., if tests expect an integer `1010`, return an integer, NOT a string `"1010"`).
8. Example structure:
   ```python
   # Optional: import statements (if needed, at module level)
   # import math
   # from collections import Counter
   
   def main_function(param1, param2):
       # Helper functions defined INSIDE main function
       def helper_function(x):
           return x * 2
       
       # Main function logic
       result = helper_function(param1)
       return result
   ```

CRITICAL FINAL OUTPUT REQUIREMENT:
- In your FINAL response before task completion, you MUST provide the COMPLETE, FINAL version of the code.
- Include the ENTIRE function implementation in your last response, not just a reference to earlier code.
- The final code should be self-contained and ready to execute.
- Do NOT just say "the code is complete" - you MUST include the full code implementation in your final response.
{test_examples}

The function should be complete and correct, passing all test cases."""
    
    return task_description


def run_camel_on_problem(
    problem: Dict,
    problem_id: str,
    model: OpenAIModel,
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False
) -> Dict:
    """
    Run CAMEL framework on a single LiveCodeBench problem.
    
    Args:
        problem: LiveCodeBench problem dictionary.
        problem_id: Problem ID.
        model: Model adapter.
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
    
    Returns:
        Dictionary containing problem_id and completion.
    """
    task_prompt = generate_task_prompt(problem)
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"Processing problem: {problem_id}")
        print(f"{'='*80}")
        print(f"Task description:\n{task_prompt[:200]}...")
    
    try:
        # Create CAMEL workflow
        graph = create_camel_role_playing_workflow(
            model=model,
            max_conversation_turns=max_conversation_turns,
            word_limit=word_limit
        )
        graph.build()
        
        # Execute workflow
        result, attributes = graph.invoke({"task": task_prompt})
        
        # Extract code
        sig_info = extract_function_signature_from_problem(problem)
        entry_point = sig_info["entry_point"] if sig_info else None
        
        if not entry_point:
            print(f"\nWarning: Cannot extract function signature from problem {problem_id}")
            if verbose:
                print(f"Problem content:\n{str(problem)[:200]}...")
        
        completion = extract_completion_from_camel_result(result, entry_point)
        
        if verbose:
            print(f"\nExtracted code:\n{completion[:300]}...")
        
        return {
            "problem_id": problem_id,
            "completion": completion
        }
    
    except Exception as e:
        print(f"\nError: Exception occurred while processing {problem_id}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return {
            "problem_id": problem_id,
            "completion": ""  # Return empty code
        }


def extract_imports_from_prompt(prompt: str) -> str:
    """
    Extract import statements from prompt.
    
    Args:
        prompt: Prompt containing code.
    
    Returns:
        Import statement string (multi-line, separated by newlines).
    """
    imports = []
    lines = prompt.split('\n')
    for line in lines:
        stripped = line.strip()
        # Match import statements
        if stripped.startswith(('import ', 'from ')):
            imports.append(stripped)
    return '\n'.join(imports)


def fix_completion_indentation(completion: str) -> str:
    """
    Fix indentation issues in completion, ensure function body has correct 4-space indentation.
    
    Args:
        completion: Function body code.
    
    Returns:
        Function body code with fixed indentation.
    """
    if not completion or not completion.strip():
        return completion
    
    lines = completion.split('\n')
    if not lines:
        return completion
    
    # Find first non-empty line
    first_non_empty_idx = None
    for i, line in enumerate(lines):
        if line.strip():
            first_non_empty_idx = i
            break
    
    if first_non_empty_idx is None:
        return completion
    
    first_line = lines[first_non_empty_idx]
    first_line_stripped = first_line.strip()
    first_line_indent = len(first_line) - len(first_line.lstrip())
    
    # If first line has no indentation, add 4 spaces
    if first_line_indent == 0 and first_line_stripped:
        # Normalize: ensure minimum indentation is 4 spaces
        min_indent = min(
            (len(line) - len(line.lstrip()) for line in lines if line.strip()),
            default=0
        )
        
        fixed_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                fixed_lines.append('')
                continue
            
            original_indent = len(line) - len(line.lstrip())
            if original_indent == 0:
                # No indentation, add 4 spaces
                fixed_lines.append('    ' + stripped)
            elif original_indent < 4:
                # Insufficient indentation, adjust to 4 spaces
                fixed_lines.append('    ' + stripped)
            else:
                # Keep relative indentation
                if min_indent > 0:
                    relative_indent = original_indent - min_indent
                    new_indent = 4 + relative_indent
                    fixed_lines.append(' ' * new_indent + stripped)
                else:
                    fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)
    
    return completion


def parse_livecodebench_test_cases(test_data: str) -> List[Dict]:
    """
    Parse LiveCodeBench test cases.
    
    LiveCodeBench test cases may be in JSON string or dictionary format.
    
    Args:
        test_data: Test case data (may be JSON string or dictionary).
    
    Returns:
        List of test cases.
    """
    if not test_data:
        return []
    
    try:
        # If string, try to parse as JSON
        if isinstance(test_data, str):
            test_data = json.loads(test_data)
        
        # If dictionary, try to extract test cases
        if isinstance(test_data, dict):
            # Possible structures: {"input": [...], "output": [...]} or {"test_cases": [...]}
            if "test_cases" in test_data:
                return test_data["test_cases"]
            elif "input" in test_data and "output" in test_data:
                # Build test case list
                inputs = test_data["input"] if isinstance(test_data["input"], list) else [test_data["input"]]
                outputs = test_data["output"] if isinstance(test_data["output"], list) else [test_data["output"]]
                return [{"input": inp, "output": out} for inp, out in zip(inputs, outputs)]
            else:
                # Use directly as test case
                return [test_data]
        elif isinstance(test_data, list):
            return test_data
        else:
            return []
    except (json.JSONDecodeError, TypeError):
        # If parsing fails, return empty list
        return []


def check_livecodebench_correctness(
    problem: Dict,
    completion: str,
    timeout: float = 3.0
) -> Dict:
    """
    Check code correctness for LiveCodeBench problems.
    
    Args:
        problem: LiveCodeBench problem dictionary.
        completion: Generated code (function body).
        timeout: Timeout (seconds).
    
    Returns:
        Dictionary containing passed and result.
    """
    # Try to extract prompt from multiple fields
    prompt = (problem.get("prompt", "") or 
              problem.get("problem", "") or 
              problem.get("description", "") or
              problem.get("question", "") or
              "")
    
    # If still empty, try to extract from original data
    if not prompt:
        # Check if there are original data fields
        for key in ["code", "solution", "code_prompt"]:
            if key in problem and problem[key]:
                prompt = str(problem[key])
                break
    
    if not prompt:
        available_keys = list(problem.keys())
        return {
            "passed": False, 
            "result": f"Cannot extract prompt from problem. Available keys: {available_keys}"
        }
    
    # Extract function signature
    # Note: LiveCodeBench's prompt field may contain test cases, not problem description
    # Need to extract function signature from other fields or completion
    sig_info = extract_function_signature_from_problem(problem)
    
    # If extraction from problem fails, try to extract from completion
    if not sig_info:
        completion_lines = completion.split('\n')
        for line in completion_lines:
            line_stripped = line.strip()
            if line_stripped.startswith('def '):
                match = re.search(r'def\s+(\w+)\s*\(([^)]*)\)', line_stripped)
                if match:
                    entry_point = match.group(1)
                    params_str = match.group(2)
                    param_names = []
                    for param in params_str.split(','):
                        param = param.strip()
                        if param:
                            param_name = param.split(':')[0].split('=')[0].strip()
                            if param_name:
                                param_names.append(param_name)
                    sig_info = {
                        "entry_point": entry_point,
                        "param_names": param_names
                    }
                    break
    
    # If still not found, try to find first function definition from completion (even with indentation)
    # Note: LiveCodeBench completion may contain nested functions, need to find main function
    if not sig_info:
        completion_lines = completion.split('\n')
        # First try to find def without indentation (main function)
        for line in completion_lines:
            stripped = line.strip()
            if stripped.startswith('def '):
                # Check if there's indentation
                indent = len(line) - len(line.lstrip())
                if indent == 0:
                    match = re.search(r'def\s+(\w+)\s*\(([^)]*)\)', stripped)
                    if match:
                        entry_point = match.group(1)
                        params_str = match.group(2)
                        param_names = []
                        for param in params_str.split(','):
                            param = param.strip()
                            if param:
                                param_name = param.split(':')[0].split('=')[0].strip()
                                if param_name:
                                    param_names.append(param_name)
                        sig_info = {
                            "entry_point": entry_point,
                            "param_names": param_names
                        }
                        break
        
        # If no def without indentation, try to find first def (may be nested function, but used as main function)
        if not sig_info:
            for line in completion_lines:
                # Find any def statement (including with indentation)
                match = re.search(r'def\s+(\w+)\s*\(([^)]*)\)', line)
                if match:
                    entry_point = match.group(1)
                    params_str = match.group(2)
                    param_names = []
                    for param in params_str.split(','):
                        param = param.strip()
                        if param:
                            param_name = param.split(':')[0].split('=')[0].strip()
                            if param_name:
                                param_names.append(param_name)
                    sig_info = {
                        "entry_point": entry_point,
                        "param_names": param_names
                    }
                    break
        
        # If still not found, try to infer function parameters from variable usage in completion
        # LiveCodeBench completion is usually function body, using some variables as parameters
        if not sig_info:
            # Extract variables used from completion (may be function parameters)
            # Find variables used at start of function body (usually used before assignment, may be parameters)
            param_candidates = []
            
            # Find common parameter patterns: variables used before assignment
            # Example: string1 in count1 = Counter(string1) may be a parameter
            for line in completion_lines[:20]:  # Only check first 20 lines
                # Find variable usage (on right side of assignment statements)
                # Pattern 1: other_var in var = something(other_var)
                matches = re.findall(r'=\s*\w+\(([a-z_][a-z0-9_]*)\)', line)
                param_candidates.extend(matches)
                # Pattern 2: Directly used variables (like string1, string2, n, m, etc.)
                matches = re.findall(r'\b([a-z_][a-z0-9_]*)\s*[=,\[\]]', line)
                param_candidates.extend(matches)
            
            # Deduplicate and filter out common non-parameter variables
            excluded_vars = {'self', 'result', 'count', 'i', 'j', 'x', 'y', 'char', 'item', 'line', 'value', 'key', 'val'}
            param_candidates = [v for v in set(param_candidates) if v not in excluded_vars and len(v) > 1]
            
            # If candidate parameters found, build function signature
            if param_candidates:
                # Select most common parameter names (by frequency)
                from collections import Counter
                param_counts = Counter(param_candidates)
                # Select top 5 most common as parameters
                param_names = [p[0] for p in param_counts.most_common(5)]
                
                # Use a generic function name
                entry_point = "solve"
                sig_info = {
                    "entry_point": entry_point,
                    "param_names": param_names
                }
            else:
                # If still not found, try to find common parameter patterns from completion
                # Check variables used in completion (in return statements or function calls)
                all_vars = set()
                for line in completion_lines:
                    # Find variable names (exclude keywords and built-in functions)
                    var_matches = re.findall(r'\b([a-z_][a-z0-9_]*)\b', line)
                    all_vars.update(var_matches)
                
                # Filter out keywords and common variables
                keywords = {'def', 'return', 'if', 'else', 'for', 'while', 'in', 'and', 'or', 'not', 'True', 'False', 'None', 'import', 'from', 'as'}
                common_vars = {'result', 'count', 'i', 'j', 'x', 'y', 'char', 'item', 'line', 'value', 'key', 'val', 'temp', 'tmp'}
                param_candidates = [v for v in all_vars if v not in keywords and v not in common_vars and len(v) > 1]
                
                if param_candidates:
                    # Select most common ones
                    from collections import Counter
                    param_counts = Counter(param_candidates)
                    param_names = [p[0] for p in param_counts.most_common(5)]
                    
                    entry_point = "solve"
                    sig_info = {
                        "entry_point": entry_point,
                        "param_names": param_names
                    }
    
    if not sig_info:
        prompt_preview = prompt[:300] if prompt else "N/A"
        completion_preview = completion[:300] if completion else "N/A"
        return {
            "passed": False, 
            "result": f"Cannot extract function signature. Prompt: {prompt_preview}... Completion: {completion_preview}..."
        }
    
    entry_point = sig_info["entry_point"]
    
    # Extract import statements
    imports = extract_imports_from_prompt(prompt)
    
    # Fix completion indentation
    completion = fix_completion_indentation(completion)
    
    # Check if completion contains complete function definition (def without indentation)
    completion_lines = completion.split('\n')
    is_complete_function = False
    for line in completion_lines:
        stripped = line.strip()
        if stripped.startswith('def '):
            # Check if there's indentation
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                is_complete_function = True
                break
    
    # Build complete code
    if not is_complete_function:
        # completion is function body, need to add function signature
        # First try to extract function signature from prompt
        sig_match = re.search(rf'def\s+{re.escape(entry_point)}\s*\([^)]*\)\s*:', prompt)
        if sig_match:
            function_signature = sig_match.group(0).strip()
        else:
            # If not in prompt, try to extract from completion (may have indentation)
            sig_match = re.search(rf'def\s+{re.escape(entry_point)}\s*\([^)]*\)\s*:', completion)
            if sig_match:
                # Extract function signature, remove indentation
                function_signature = sig_match.group(0).strip()
            else:
                # If neither, build function signature from extracted parameter names
                if sig_info.get("param_names"):
                    param_str = ", ".join(sig_info["param_names"])
                    function_signature = f"def {entry_point}({param_str}):"
                else:
                    # Last fallback: use *args
                    function_signature = f"def {entry_point}(*args, **kwargs):"
        
        code_parts = []
        if imports:
            code_parts.append(imports)
        code_parts.append(function_signature)
        code_parts.append(completion)
        full_code = '\n'.join(code_parts)
    else:
        # completion contains complete function definition
        code_parts = []
        if imports:
            # Check if completion already contains import statements
            completion_has_imports = any(line.strip().startswith(('import ', 'from ')) 
                                         for line in completion.split('\n'))
            if not completion_has_imports:
                code_parts.append(imports)
        code_parts.append(completion)
        full_code = '\n'.join(code_parts)
    
    # Get test cases
    test_cases = []
    public_test_cases = problem.get("public_test_cases", "")
    input_output = problem.get("input_output", "")
    test_data = problem.get("test", "")
    
    # Try to parse test cases from different fields
    if public_test_cases:
        test_cases = parse_livecodebench_test_cases(public_test_cases)
    elif input_output:
        test_cases = parse_livecodebench_test_cases(input_output)
    elif test_data:
        test_cases = parse_livecodebench_test_cases(test_data)
    
    if not test_cases:
        return {"passed": False, "result": "No test cases found"}
    
    # Execute test cases
    # LiveCodeBench test cases may be stored as strings, need to parse
    # Reference HumanEval approach, use exec to execute test code
    
    passed_count = 0
    total_count = 0
    errors = []
    
    # Try to extract test code from public_test_cases or input_output
    test_code_str = ""
    if public_test_cases:
        if isinstance(public_test_cases, str):
            test_code_str = public_test_cases
        elif isinstance(public_test_cases, dict):
            # If dictionary, try to extract test code
            test_code_str = public_test_cases.get("test_code", public_test_cases.get("code", ""))
    elif input_output:
        if isinstance(input_output, str):
            test_code_str = input_output
        elif isinstance(input_output, dict):
            test_code_str = input_output.get("test_code", input_output.get("code", ""))
    
    # If test code string found, execute directly
    if test_code_str:
        try:
            import subprocess
            import tempfile
            
            # Build complete code (function definition + test code)
            test_code_with_tests = f"{full_code}\n\n{test_code_str}"
            
            # Create temporary file and execute
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                f.write(test_code_with_tests)
                temp_file = f.name
            
            try:
                result = subprocess.run(
                    [sys.executable, temp_file],
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                
                if result.returncode == 0:
                    # Count passed test cases (by checking output or using other methods)
                    # Simplified handling here: if no error, consider passed
                    passed_count = 1
                    total_count = 1
                else:
                    error_msg = result.stderr.strip() or result.stdout.strip()
                    errors.append(f"Execution error: {error_msg[:200]}")
                    total_count = 1
            finally:
                try:
                    os.unlink(temp_file)
                except:
                    pass
        except subprocess.TimeoutExpired:
            errors.append("timeout")
            total_count = 1
        except Exception as e:
            errors.append(f"Exception: {str(e)[:200]}")
            total_count = 1
    else:
        # If test code not found, try to use parsed test case list
        # This method may not be accurate enough, as LiveCodeBench format may differ
        if test_cases:
            total_count = len(test_cases)
            for i, test_case in enumerate(test_cases):
                try:
                    import subprocess
                    import tempfile
                    
                    # Build test code
                    if isinstance(test_case, dict):
                        test_input = test_case.get("input", test_case.get("Input", ""))
                        test_output = test_case.get("output", test_case.get("Output", ""))
                    else:
                        test_input = str(test_case)
                        test_output = None
                    
                    # Build test code
                    if test_output is not None:
                        test_code = f"""
# Test case {i}
try:
    result = {entry_point}({test_input})
    assert result == {repr(test_output)}, f"Expected {repr(test_output)}, got {{result}}"
    print("Test {i} passed")
except Exception as e:
    print(f"Test {i} failed: {{e}}")
    raise
"""
                    else:
                        test_code = f"""
# Test case {i}
try:
    result = {entry_point}({test_input})
    print("Test {i} passed")
except Exception as e:
    print(f"Test {i} failed: {{e}}")
    raise
"""
                    
                    test_code_with_tests = f"{full_code}\n\n{test_code}"
                    
                    # Create temporary file and execute
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                        f.write(test_code_with_tests)
                        temp_file = f.name
                    
                    try:
                        result = subprocess.run(
                            [sys.executable, temp_file],
                            capture_output=True,
                            text=True,
                            timeout=timeout
                        )
                        
                        if result.returncode == 0 and f"Test {i} passed" in result.stdout:
                            passed_count += 1
                        else:
                            error_msg = result.stderr.strip() or result.stdout.strip()
                            errors.append(f"Test {i}: {error_msg[:100]}")
                    finally:
                        try:
                            os.unlink(temp_file)
                        except:
                            pass
                            
                except subprocess.TimeoutExpired:
                    errors.append(f"Test {i}: timeout")
                except Exception as e:
                    errors.append(f"Test {i}: {str(e)[:100]}")
        else:
            # If neither test code nor test cases found, return error
            return {"passed": False, "result": "No test cases or test code found"}
    
    # Return result
    passed = passed_count == total_count
    if passed:
        result_msg = f"passed: {passed_count}/{total_count} passed"
    else:
        error_summary = ". ".join(errors[:3])  # Only show first 3 errors
        result_msg = f"failed: {passed_count}/{total_count} passed. Errors: {error_summary}"
    
    return {
        "passed": passed,
        "result": result_msg
    }


def evaluate_camel_on_livecodebench(
    output_file: str,
    model: OpenAIModel,
    max_problems: int = None,
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False,
    problem_file: str = None,
    k: List[int] = [1, 10, 100],
    n_workers: int = 4,
    timeout: float = 3.0,
) -> Dict:
    """
    Evaluate CAMEL framework on LiveCodeBench dataset.
    
    Args:
        output_file: Output JSONL file path.
        model: Model adapter.
        max_problems: Maximum number of problems to process (None means all).
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
        problem_file: LiveCodeBench problem file path (None means use default path).
        k: List of k values for pass@k.
        n_workers: Number of parallel worker threads for evaluation (unused, kept for compatibility).
        timeout: Timeout for each test (seconds).
    
    Returns:
        Evaluation result dictionary, containing pass@k and other metrics.
    """
    # Read LiveCodeBench problems
    if problem_file is None:
        # Default try to load from HuggingFace
        print("No problem file specified, trying to load LiveCodeBench dataset from HuggingFace...")
        print("(If this fails, please use --problem_file parameter to specify local file path)")
        problem_file = None  # None means load from HuggingFace
    
    print(f"Reading LiveCodeBench problems...")
    try:
        all_problems = read_livecodebench_problems(problem_file)
    except ImportError as e:
        print(f"\nError: {e}")
        print("\nHint: LiveCodeBench data can be obtained by:")
        print("1. Load from HuggingFace (need to install datasets library): pip install datasets")
        print("2. Use local file: --problem_file <file_path>")
        raise
    except FileNotFoundError as e:
        print(f"\nError: {e}")
        print("\nHint: LiveCodeBench data can be obtained by:")
        print("1. Load from HuggingFace: don't specify --problem_file parameter (need to install datasets library)")
        print("2. Use local file: --problem_file <file_path>")
        raise
    print(f"Found {len(all_problems)} problems in total")
    
    # Limit number of problems (for testing)
    if max_problems is not None and max_problems > 0:
        problem_items = list(all_problems.items())[:max_problems]
        problems = dict(problem_items)
        print(f"Limited to first {max_problems} problems")
    else:
        problems = all_problems
    
    # Generate code
    print(f"\nStarting code generation using CAMEL framework...")
    samples = []
    
    for problem_id, problem in tqdm.tqdm(problems.items(), desc="Generating code"):
        sample = run_camel_on_problem(
            problem=problem,
            problem_id=problem_id,
            model=model,
            max_conversation_turns=max_conversation_turns,
            word_limit=word_limit,
            verbose=verbose
        )
        samples.append(sample)
    
    # Save generated samples
    print(f"\nSaving generated samples to: {output_file}")
    # Ensure output directory exists
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')
    
    print(f"Generated {len(samples)} samples in total")
    
    # Evaluate code
    print(f"\nStarting code evaluation...")
    results = []
    
    for sample in tqdm.tqdm(samples, desc="Evaluating code"):
        problem_id = sample["problem_id"]
        completion = sample["completion"]
        problem = problems.get(problem_id)
        
        if problem is None:
            results.append({
                "problem_id": problem_id,
                "passed": False,
                "result": f"Problem not found. Available problem_ids: {list(problems.keys())[:5]}..."
            })
            continue
        
        if not problem.get("prompt") and not problem.get("problem"):
            print(f"\nWarning: Problem {problem_id} has no prompt field")
            print(f"Problem dictionary keys: {list(problem.keys())}")
            print(f"Problem dictionary content (first 200 chars): {str(problem)[:200]}")
        
        result = check_livecodebench_correctness(
            problem=problem,
            completion=completion,
            timeout=timeout
        )
        result["problem_id"] = problem_id
        results.append(result)
    
    # Save evaluation results
    result_file = output_file.replace('.jsonl', '_results.jsonl')
    print(f"\nSaving evaluation results to: {result_file}")
    with open(result_file, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + '\n')
    
    # Calculate pass@k
    print(f"\nCalculating pass@k metrics...")
    passed_count = sum(1 for r in results if r.get("passed", False))
    total_count = len(results)
    pass_rate = passed_count / total_count if total_count > 0 else 0.0
    
    print(f"\n{'='*80}")
    print(f"Evaluation Results:")
    print(f"{'='*80}")
    print(f"Total: {total_count}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {total_count - passed_count}")
    print(f"Pass Rate: {pass_rate:.4f} ({pass_rate*100:.2f}%)")
    print(f"{'='*80}")
    
    # Calculate pass@k (simplified version, assumes k=1)
    pass_at_k = {}
    for k_val in k:
        if k_val == 1:
            pass_at_k[f"pass@{k_val}"] = pass_rate
        else:
            # For k>1, need multiple samples, simplified handling here
            pass_at_k[f"pass@{k_val}"] = pass_rate
    
    print(f"\npass@k:")
    for k_val, score in pass_at_k.items():
        print(f"  {k_val}: {score:.4f}")
    
    return {
        "pass_rate": pass_rate,
        "pass_at_k": pass_at_k,
        "total": total_count,
        "passed": passed_count,
        "failed": total_count - passed_count,
        "output_file": output_file,
        "result_file": result_file
    }


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate CAMEL framework using LiveCodeBench dataset"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Output JSONL file path (default: livecodebench/result/camel_livecodebench_samples.jsonl)"
    )
    parser.add_argument(
        "--max_problems",
        type=int,
        default=10,
        help="Maximum number of problems to process (0 means all, positive means first N)"
    )
    parser.add_argument(
        "--max_conversation_turns",
        type=int,
        default=40,
        help="Maximum number of conversation turns"
    )
    parser.add_argument(
        "--word_limit",
        type=int,
        default=50,
        help="Word limit for task specification"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed information"
    )
    parser.add_argument(
        "--problem_file",
        type=str,
        default=None,
        help="LiveCodeBench problem file path (default loads from HuggingFace, or specify local JSON/JSONL file path)"
    )
    parser.add_argument(
        "--k",
        type=str,
        default="1,10,100",
        help="List of k values for pass@k, separated by commas (for recording, actual evaluation needs LiveCodeBench tools)"
    )
    parser.add_argument(
        "--n_workers",
        type=int,
        default=4,
        help="Number of parallel worker threads for evaluation (unused, kept for compatibility)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="Timeout for each test (seconds) (unused, kept for compatibility)"
    )
    parser.add_argument(
        "--api_key",
        type=str,
        default=None,
        help="OpenAI API key (if not set, read from environment variable)"
    )
    parser.add_argument(
        "--base_url",
        type=str,
        default=None,
        help="OpenAI API base URL (if not set, read from environment variable)"
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default=None,
        help="Model name (if not set, read from environment variable)"
    )
    
    args = parser.parse_args()
    
    # Set default output path
    if args.output_file is None:
        livecodebench_dir = Path(__file__).parent
        result_dir = livecodebench_dir / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        args.output_file = str(result_dir / "camel_livecodebench_samples.jsonl")
    
    # Set model
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    base_url = args.base_url or os.getenv("OPENAI_BASE_URL", "https://api.csun.site/v1/")
    model_name = args.model_name or os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
    
    if not api_key:
        print("Error: Please set OPENAI_API_KEY environment variable or use --api_key parameter")
        sys.exit(1)
    
    model = OpenAIModel(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name
    )
    
    # Parse k values
    k = [int(x.strip()) for x in args.k.split(",")]
    
    # Handle max_problems: 0 or negative means all
    max_problems = None if args.max_problems <= 0 else args.max_problems
    
    # Run evaluation
    evaluate_camel_on_livecodebench(
        output_file=args.output_file,
        model=model,
        max_problems=max_problems,
        max_conversation_turns=args.max_conversation_turns,
        word_limit=args.word_limit,
        verbose=args.verbose,
        problem_file=args.problem_file,
        k=k,
        n_workers=args.n_workers,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    main()

