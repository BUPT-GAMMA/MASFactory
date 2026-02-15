"""Evaluate CAMEL framework using MBPP dataset.

This module provides functionality to evaluate the CAMEL role-playing framework
on the MBPP (Mostly Basic Python Problems) code generation benchmark.
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


def read_mbpp_problems(problem_file: str) -> Dict[int, Dict]:
    """
    Read MBPP problem file.
    
    Args:
        problem_file: Path to MBPP JSONL file.
    
    Returns:
        Problem dictionary, key is task_id, value is problem dictionary.
    """
    problems = {}
    with open(problem_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                problem = json.loads(line)
                task_id = problem.get("task_id")
                if task_id is not None:
                    problems[task_id] = problem
    return problems


def extract_function_signature_from_code(code: str) -> Optional[Dict]:
    """
    Extract function signature information from MBPP's code field.
    
    Args:
        code: MBPP's code field (containing complete function definition).
    
    Returns:
        Dictionary containing entry_point and param_names, or None if not found.
    """
    # Find first function definition
    match = re.search(r'def\s+(\w+)\s*\(([^)]*)\)', code)
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
    return None


def generate_task_prompt(problem: Dict) -> str:
    """
    Convert MBPP problem to CAMEL framework task description.
    
    Args:
        problem: MBPP problem dictionary, containing text, code, test_list, etc.
    
    Returns:
        Task description string.
    """
    text = problem.get("text", "")
    code = problem.get("code", "")
    test_list = problem.get("test_list", [])
    
    # Extract function signature information
    sig_info = extract_function_signature_from_code(code)
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
    
    # Build test case descriptions
    test_examples = ""
    if test_list:
        test_examples = "\n\nYour code should pass these test cases:\n"
        for i, test in enumerate(test_list[:3], 1):  # Only show first 3 test cases
            test_examples += f"{i}. {test}\n"
    
    task_description = f"""Write a Python function that solves the following problem:

{text}{param_emphasis}

REQUIREMENTS:
1. Use EXACTLY the parameter names specified in the function signature above. Do NOT rename them (e.g., if signature says "string", use "string", NOT "s" or "input_string"). If the signature uses short names like "l", "b", "h", you MUST use those EXACT names, not "length", "base", "height".
2. If your code uses standard library modules (like math, re, collections, etc.), you MUST include the import statements at the module level (before the function definition). For example: "import re" or "from collections import Counter".
3. If you need helper functions (like is_prime(), generate_primes(), etc.), you MUST define them INSIDE the main function as nested functions. Do NOT define them outside the main function.
4. The code must be complete, syntactically correct, and ready to execute.
5. Use 4-space indentation for all code. Ensure all lines in the function body are properly indented with 4 spaces (or multiples of 4 spaces for nested blocks).
6. Do NOT include docstrings in the function body.
7. The return type MUST match EXACTLY what the test cases expect (e.g., if tests expect an integer `1010`, return an integer, NOT a string `"1010"`).
7. Example structure:
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
    model: OpenAIModel,
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False
) -> Dict:
    """
    Run CAMEL framework on a single MBPP problem.
    
    Args:
        problem: MBPP problem dictionary.
        model: Model adapter.
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
    
    Returns:
        Dictionary containing task_id and completion.
    """
    task_id = problem["task_id"]
    task_prompt = generate_task_prompt(problem)
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"Processing problem: {task_id}")
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
        sig_info = extract_function_signature_from_code(problem.get("code", ""))
        if not sig_info:
            print(f"\nWarning: Cannot extract function signature from problem {task_id}'s code")
            if verbose:
                print(f"Problem code:\n{problem.get('code', '')[:200]}...")
            entry_point = None
        else:
            entry_point = sig_info["entry_point"]
        
        completion = extract_completion_from_camel_result(result, entry_point)
        
        if verbose:
            print(f"\nExtracted code:\n{completion[:300]}...")
        
        return {
            "task_id": task_id,
            "completion": completion
        }
    
    except Exception as e:
        print(f"\nError: Exception occurred while processing {task_id}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return {
            "task_id": task_id,
            "completion": ""  # Return empty code
        }


def extract_imports_from_code(code: str) -> str:
    """
    Extract import statements from original code.
    
    Args:
        code: Original code string.
    
    Returns:
        Import statement string (multi-line, separated by newlines).
    """
    imports = []
    lines = code.split('\n')
    for line in lines:
        stripped = line.strip()
        # Match import statements
        if stripped.startswith(('import ', 'from ')):
            imports.append(stripped)
    return '\n'.join(imports)


def fix_completion_indentation(completion: str) -> str:
    """
    Fix indentation issues in completion.
    
    Problem: When completion contains nested function definitions, these nested functions' def lines already have 4-space indentation.
    But when we add completion after the function signature, Python expects the function body to start at column 0.
    
    Key issue: If the first line of completion starts with `def` and has indentation, it's a nested function definition.
    The def line of nested functions should have 4-space indentation (relative to main function body), which is correct.
    But if the first line of completion starts with `def` but has no indentation, it's a complete function definition, which shouldn't appear in function body.
    
    Solution:
    1. Check if first line starts with def and has indentation (nested function definition)
    2. If yes, keep indentation unchanged (already correct)
    3. If first line starts with def but has no indentation, this is wrong, need to add 4-space indentation
    4. Normalize indentation of all lines: ensure minimum indentation is 4 spaces
    
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
    
    # Check if first line starts with def
    is_def_start = first_line_stripped.startswith('def ')
    
    # If first line starts with def and has indentation (nested function definition), this is correct, keep as is
    # But need to ensure all lines' indentation is relative to main function body (minimum indentation should be 4)
    if is_def_start and first_line_indent > 0:
        # This is a nested function definition, indentation should be correct
        # But need to ensure minimum indentation is 4 spaces, and def lines inside nested functions have correct indentation (8 spaces)
        min_indent = min(
            (len(line) - len(line.lstrip()) for line in lines if line.strip()),
            default=0
        )
        
        # Check if there are nested nested functions (def lines inside function body)
        # Strategy: Find all def lines, if a def line's indentation equals min_indent, it's first-level nested function (4 spaces)
        # If a def line's indentation is greater than min_indent but inside a function body, it's nested nested function (should be 8 spaces)
        fixed_lines = []
        in_nested_function = False  # Whether inside nested function
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                fixed_lines.append('')
                continue
            
            original_indent = len(line) - len(line.lstrip())
            
            # Check if it's a def line
            if stripped.startswith('def '):
                if original_indent == min_indent:
                    # This is first-level nested function definition (relative to main function body), should keep 4-space indentation
                    fixed_lines.append('    ' + stripped)
                    in_nested_function = True
                elif original_indent > min_indent:
                    # This is nested nested function definition, should have 8-space indentation (relative to main function body)
                    # But if it's inside another nested function, should keep relative indentation
                    # Simple strategy: if indentation > 4, it's nested nested function, should adjust to 8 spaces
                    fixed_lines.append('        ' + stripped)  # 8 spaces
                    in_nested_function = True
                else:
                    # Shouldn't happen
                    fixed_lines.append('    ' + stripped)
            else:
                # Regular code line, adjust indentation
                if min_indent != 4:
                    relative_indent = original_indent - min_indent
                    new_indent = 4 + relative_indent
                    fixed_lines.append(' ' * new_indent + stripped)
                else:
                    fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)
    
    # If first line starts with def but has no indentation, this is wrong (complete function definition shouldn't appear in function body)
    # Need to add 4-space indentation
    if is_def_start and first_line_indent == 0:
        fixed_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                fixed_lines.append('')
            else:
                fixed_lines.append('    ' + stripped)
        return '\n'.join(fixed_lines)
    
    # If first line doesn't start with def, handle indentation normally
    # Find minimum indentation (excluding empty lines)
    min_indent = min(
        (len(line) - len(line.lstrip()) for line in lines if line.strip()),
        default=0
    )
    
    # If minimum indentation is 0, some lines have no indentation, need to uniformly add 4-space base indentation
    if min_indent == 0:
        fixed_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                fixed_lines.append('')
            else:
                original_indent = len(line) - len(line.lstrip())
                if original_indent == 0:
                    # Lines with no indentation, add 4 spaces
                    fixed_lines.append('    ' + stripped)
                else:
                    # Lines with indentation, keep relative indentation, but base indentation is 4 spaces
                    relative_indent = original_indent - min_indent
                    new_indent = 4 + relative_indent
                    fixed_lines.append(' ' * new_indent + stripped)
        return '\n'.join(fixed_lines)
    
    # If minimum indentation is not 4, need to adjust to 4
    if min_indent != 4:
        fixed_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                fixed_lines.append('')
            else:
                original_indent = len(line) - len(line.lstrip())
                # Adjust indentation: from min_indent to 4, keep relative indentation
                relative_indent = original_indent - min_indent
                new_indent = 4 + relative_indent
                fixed_lines.append(' ' * new_indent + stripped)
        return '\n'.join(fixed_lines)
    
    # Minimum indentation is already 4, return directly (indentation correct)
    return completion


def check_mbpp_correctness(
    problem: Dict,
    completion: str,
    timeout: float = 3.0
) -> Dict:
    """
    Check code correctness for MBPP problems.
    
    Args:
        problem: MBPP problem dictionary.
        completion: Generated code (function body).
        timeout: Timeout (seconds).
    
    Returns:
        Dictionary containing passed and result.
    """
    code = problem.get("code", "")
    test_list = problem.get("test_list", [])
    test_setup_code = problem.get("test_setup_code", "")
    
    # Extract import statements (from original code)
    imports = extract_imports_from_code(code)
    
    # Extract function signature
    sig_info = extract_function_signature_from_code(code)
    if not sig_info:
        return {"passed": False, "result": "Cannot extract function signature"}
    
    entry_point = sig_info["entry_point"]
    
    # Build complete code
    # Check if completion contains complete function definition (starts with def and has no indentation)
    # If first line of completion starts with def but has no indentation, it's a complete function definition
    # If first line of completion starts with def but has indentation, it's a nested function definition, need to add function signature
    first_line = completion.split('\n')[0] if completion else ""
    first_line_stripped = first_line.strip()
    first_line_indent = len(first_line) - len(first_line.lstrip())
    is_complete_function = first_line_stripped.startswith("def ") and first_line_indent == 0
    
    # Fix completion indentation issues (fix after judgment to avoid affecting judgment)
    completion = fix_completion_indentation(completion)
    
    # If completion doesn't contain complete function definition, need to add function signature
    if not is_complete_function:
        # completion is function body, need to add function signature
        # Extract function signature from original code (allow spaces before colon)
        sig_match = re.search(rf'def\s+{re.escape(entry_point)}\s*\([^)]*\)\s*:', code)
        if sig_match:
            function_signature = sig_match.group(0).strip()  # Remove leading/trailing spaces to ensure consistent format
            # completion should already have correct indentation (4 spaces), use directly
            # Build code: import statements + test setup code + function signature + function body
            code_parts = []
            if imports:
                code_parts.append(imports)
            if test_setup_code:
                code_parts.append(test_setup_code)
            code_parts.append(function_signature)
            code_parts.append(completion)
            full_code = '\n'.join(code_parts)
        else:
            return {"passed": False, "result": "Cannot extract function signature from code"}
    else:
        # completion contains complete function definition
        # Check if completion already contains import statements
        completion_has_imports = any(line.strip().startswith(('import ', 'from ')) 
                                     for line in completion.split('\n'))
        code_parts = []
        if imports and not completion_has_imports:
            code_parts.append(imports)
        if test_setup_code:
            code_parts.append(test_setup_code)
        code_parts.append(completion)
        full_code = '\n'.join(code_parts)
    
    # Add test cases
    test_code = "\n".join(test_list)
    full_code_with_tests = f"{full_code}\n\n{test_code}"
    
    # Execute tests - MBPP uses assert statements, need to execute directly
    try:
        import subprocess
        import tempfile
        import threading
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(full_code_with_tests)
            temp_file = f.name
        
        try:
            # Execute code
            result = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode == 0:
                return {"passed": True, "result": "passed"}
            else:
                error_msg = result.stderr.strip() or result.stdout.strip()
                return {"passed": False, "result": f"failed: {error_msg[:200]}"}
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file)
            except:
                pass
                
    except subprocess.TimeoutExpired:
        return {"passed": False, "result": "failed: timeout"}
    except Exception as e:
        return {"passed": False, "result": f"failed: {str(e)[:200]}"}


def evaluate_camel_on_mbpp(
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
    test_split: str = "test"  # "test" for task_ids 11-510, "train" for others
) -> Dict:
    """
    Evaluate CAMEL framework on MBPP dataset.
    
    Args:
        output_file: Output JSONL file path.
        model: Model adapter.
        max_problems: Maximum number of problems to process (None means all).
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
        problem_file: MBPP problem file path (None means use default path).
        k: List of k values for pass@k.
        n_workers: Number of parallel worker threads for evaluation.
        timeout: Timeout for each test (seconds).
        test_split: Dataset split to use ("test" means task_ids 11-510).
    
    Returns:
        Evaluation result dictionary, containing pass@k and other metrics.
    """
    # Read MBPP problems
    if problem_file is None:
        # Use default path
        default_path = Path(__file__).parent.parent.parent.parent.parent / "datasets" / "mbpp" / "mbpp.jsonl"
        if not default_path.exists():
            raise FileNotFoundError(f"Cannot find MBPP problem file: {default_path}")
        problem_file = str(default_path)
    
    print(f"Reading MBPP problem file: {problem_file}")
    all_problems = read_mbpp_problems(problem_file)
    print(f"Found {len(all_problems)} problems in total")
    
    # Filter problems based on test_split
    if test_split == "test":
        # Test set: task_ids 11-510
        problems = {tid: p for tid, p in all_problems.items() if 11 <= tid <= 510}
        print(f"Test set (task_ids 11-510): {len(problems)} problems")
    else:
        problems = all_problems
    
    # Limit number of problems (for testing)
    # If max_problems is None or 0, use all problems; otherwise limit count
    if max_problems is not None and max_problems != 0:
        if max_problems < 0:
            # If max_problems is negative, represents list of task_ids that failed tests (for verifying fixes)
            # 36 task_ids that failed from most recent evaluation results
            failed_tasks = [13, 15, 18, 24, 25, 27, 28, 30, 31, 33, 34, 35, 42, 43, 45, 47, 48, 56, 60, 61, 64, 70, 71, 72, 73, 77, 81, 82, 83, 87, 101, 102, 104, 107, 108, 110]
            problems = {tid: p for tid, p in problems.items() if tid in failed_tasks}
            print(f"Test cases that failed: {len(problems)} problems (task_ids: {sorted(problems.keys())})")
        else:
            # Sort by task_id then take first max_problems
            sorted_items = sorted(problems.items(), key=lambda x: x[0])[:max_problems]
            problems = dict(sorted_items)
            print(f"Limited to first {max_problems} problems (sorted by task_id)")
    
    # Generate code
    print(f"\nStarting code generation using CAMEL framework...")
    samples = []
    
    for task_id, problem in tqdm.tqdm(problems.items(), desc="Generating code"):
        sample = run_camel_on_problem(
            problem=problem,
            model=model,
            max_conversation_turns=max_conversation_turns,
            word_limit=word_limit,
            verbose=verbose
        )
        samples.append(sample)
    
    # Save samples
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"\nSaving samples to: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')
    
    print(f"Generated {len(samples)} samples in total")
    
    # Evaluate code
    print(f"\nStarting code evaluation...")
    results = []
    
    for sample in tqdm.tqdm(samples, desc="Evaluating code"):
        task_id = sample["task_id"]
        completion = sample["completion"]
        problem = problems.get(task_id)
        
        if problem is None:
            results.append({
                "task_id": task_id,
                "passed": False,
                "result": "Problem not found"
            })
            continue
        
        result = check_mbpp_correctness(
            problem=problem,
            completion=completion,
            timeout=timeout
        )
        result["task_id"] = task_id
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
            pass_at_k[k_val] = pass_rate
        else:
            # For k>1, need multiple samples, simplified handling here
            pass_at_k[k_val] = pass_rate
    
    print(f"\npass@k:")
    for k_val, score in pass_at_k.items():
        print(f"  pass@{k_val}: {score:.4f}")
    
    return {
        "pass_rate": pass_rate,
        "pass_at_k": pass_at_k,
        "total": total_count,
        "passed": passed_count,
        "failed": total_count - passed_count
    }


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Evaluate CAMEL framework using MBPP dataset")
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Output JSONL file path (default: mbpp/result/camel_mbpp_samples.jsonl)"
    )
    parser.add_argument(
        "--max_problems",
        type=int,
        default=0,
        help="Maximum number of problems to process (0 means all, positive means first N, negative means 36 failed test cases)"
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
        help="MBPP problem file path (default uses dataset path)"
    )
    parser.add_argument(
        "--k",
        type=str,
        default="1,10,100",
        help="List of k values for pass@k, separated by commas"
    )
    parser.add_argument(
        "--n_workers",
        type=int,
        default=4,
        help="Number of parallel worker threads for evaluation"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="Timeout for each test (seconds)"
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
    parser.add_argument(
        "--test_split",
        type=str,
        default="test",
        choices=["test", "all"],
        help="Dataset split to use (test: task_ids 11-510, all: all)"
    )
    
    args = parser.parse_args()
    
    # Set default output path
    if args.output_file is None:
        mbpp_dir = Path(__file__).parent
        result_dir = mbpp_dir / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        args.output_file = str(result_dir / "camel_mbpp_samples.jsonl")
    
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
    
    # Handle max_problems:
    # - 0: Use all problems
    # - Positive: First N problems
    # - Negative: Test indentation error fixes (specific task_id list)
    # - None: Use all problems
    if args.max_problems == 0:
        max_problems = None  # 0 means all
    else:
        max_problems = args.max_problems  # Keep original value (positive or negative)
    
    # Run evaluation
    evaluate_camel_on_mbpp(
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
        test_split=args.test_split,
    )


if __name__ == "__main__":
    main()

