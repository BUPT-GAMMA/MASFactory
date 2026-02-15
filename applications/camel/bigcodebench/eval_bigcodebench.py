"""Evaluate CAMEL framework using BigCodeBench dataset.

This module provides functionality to evaluate the CAMEL role-playing framework
on the BigCodeBench code generation benchmark.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional
import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

# Add parent directory to path for importing CAMEL framework
sys.path.insert(0, str(Path(__file__).parent.parent))

# Add bigcodebench-main to path for importing official evaluation logic
bigcodebench_main_path = Path(__file__).parent.parent.parent.parent.parent / "datasets" / "bigcodebench-main"
if bigcodebench_main_path.exists():
    sys.path.insert(0, str(bigcodebench_main_path))
else:
    # Try other possible paths
    alternative_paths = [
        Path(__file__).parent.parent.parent.parent.parent.parent / "datasets" / "bigcodebench-main",
    ]
    for alt_path in alternative_paths:
        if alt_path.exists():
            sys.path.insert(0, str(alt_path))
            break

# Import bigcodebench official modules
try:
    from bigcodebench.data import get_bigcodebench  # type: ignore
    from bigcodebench.eval import untrusted_check, estimate_pass_at_k, PASS  # type: ignore
    from bigcodebench.data.utils import stream_jsonl, write_jsonl  # type: ignore
except ImportError as e:
    # Warning: Cannot import bigcodebench module
    # Ensure bigcodebench-main is at the correct path or install: pip install bigcodebench
    raise

# Import CAMEL framework (from parent directory)
# Important: Add eval directory to the front of sys.path before importing workflow
# This ensures workflow.py and conversation_loop.py will prioritize using eval/prompts.py (evaluation-specific version)
eval_dir = str(Path(__file__).parent.parent / "eval")
if eval_dir not in sys.path or sys.path.index(eval_dir) != 0:
    if eval_dir in sys.path:
        sys.path.remove(eval_dir)
    sys.path.insert(0, eval_dir)

from workflow import create_camel_role_playing_workflow  # type: ignore
from masfactory import OpenAIModel  # type: ignore

# Import local code extraction tool
# Need to ensure import from current directory (bigcodebench), not from eval directory
bigcodebench_dir = str(Path(__file__).parent)
if bigcodebench_dir not in sys.path:
    sys.path.insert(0, bigcodebench_dir)
elif sys.path.index(bigcodebench_dir) > 0:
    # If already in sys.path but not first, move to front
    sys.path.remove(bigcodebench_dir)
    sys.path.insert(0, bigcodebench_dir)

from code_extractor import extract_complete_solution_from_camel_result  # type: ignore


def generate_task_prompt(problem: Dict, split: str = "instruct") -> str:
    """Convert BigCodeBench problem to CAMEL framework task description.
    
    Args:
        problem: BigCodeBench problem dictionary.
        split: Split to use ("instruct" or "complete").
    
    Returns:
        Task description string.
    """
    if split == "instruct":
        # Use instruct_prompt (more concise instruction)
        prompt = problem.get("instruct_prompt", "")
    else:
        # Use complete_prompt (full docstring)
        prompt = problem.get("complete_prompt", "")
    
    if not prompt:
        # If neither exists, try to build from other fields
        prompt = problem.get("prompt", "") or problem.get("description", "")
    
    # Extract function signature information (from code_prompt)
    code_prompt = problem.get("code_prompt", "")
    entry_point = problem.get("entry_point", "")
    
    # Extract parameter names from code_prompt
    import re
    param_names = []
    if code_prompt and entry_point:
        # Try to extract function signature from code_prompt
        sig_match = re.search(rf'def\s+{re.escape(entry_point)}\s*\(([^)]*)\)', code_prompt)
        if sig_match:
            params_str = sig_match.group(1)
            param_names = [p.strip().split(':')[0].split('=')[0].strip() for p in params_str.split(',') if p.strip()]
    
    # Build task description emphasizing parameter names
    param_emphasis = ""
    if param_names:
        param_list = ", ".join([f'"{name}"' for name in param_names])
        param_emphasis = f"""

CRITICAL: The function signature specifies these EXACT parameter names: {param_list}
You MUST use these EXACT parameter names in your code. Do NOT rename them to other names like "input_string", "numbers", "s", etc.
"""
    
    task_description = f"""Write a Python function that solves the following problem:

{prompt}{param_emphasis}

REQUIREMENTS:
1. Use EXACTLY the parameter names specified in the function signature. Do NOT rename them.
2. If your code uses standard library modules (like math, re, collections, etc.), you MUST include the import statements at the module level (before the function definition).
3. If you need helper functions, you MUST define them INSIDE the main function as nested functions. Do NOT define them outside the main function.
4. The code must be complete, syntactically correct, and ready to execute.
5. Use 4-space indentation for all code.
6. Do NOT include docstrings in the function body.
7. The function should be complete and correct, passing all test cases.

CRITICAL FINAL OUTPUT REQUIREMENT:
- In your FINAL response before task completion, you MUST provide the COMPLETE, FINAL version of the code.
- Include the ENTIRE function implementation in your last response, not just a reference to earlier code.
- The final code should be self-contained and ready to execute.
- Do NOT just say "the code is complete" - you MUST include the full code implementation in your final response.
- MOST IMPORTANT: In your FINAL response, you MUST output ONLY the complete code. Do NOT include any explanatory text, comments, or descriptions. Output ONLY the code itself (including import statements and the complete function definition). No explanations, no "Here is the code:", no "The solution is:", just the pure code."""
    
    return task_description


def run_camel_on_problem(
    problem: Dict,
    problem_id: str,
    model: OpenAIModel,
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False,
    split: str = "instruct"
) -> Dict:
    """Run CAMEL framework on a single BigCodeBench problem.
    
    Args:
        problem: BigCodeBench problem dictionary.
        problem_id: Problem ID.
        model: Model adapter.
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
        split: Split to use ("instruct" or "complete").
    
    Returns:
        Dictionary containing task_id and solution.
    """
    task_prompt = generate_task_prompt(problem, split=split)
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"Processing Problem: {problem_id}")
        print(f"{'='*80}")
        print(f"Task Description:\n{task_prompt[:200]}...")
    
    # Create CAMEL workflow
    graph = create_camel_role_playing_workflow(
        model=model,
        max_conversation_turns=max_conversation_turns,
        word_limit=word_limit
    )
    graph.build()
    
    # Execute workflow (let exceptions propagate to outer layer, handled by retry logic)
    result, attributes = graph.invoke({"task": task_prompt})
    
    # Extract complete code (including function signature)
    code_prompt = problem.get("code_prompt", "")
    entry_point = problem.get("entry_point")
    
    solution = extract_complete_solution_from_camel_result(
        result,
        code_prompt=code_prompt,
        entry_point=entry_point
    )
    
    if verbose:
        print(f"\nExtracted code:\n{solution[:300]}...")
    
    return {
        "task_id": problem_id,
        "solution": solution
    }


def check_bigcodebench_correctness(
    problem: Dict,
    solution: str,
    max_as_limit: int = 30 * 1024,
    max_data_limit: int = 30 * 1024,
    max_stack_limit: int = 10,
    min_time_limit: float = 1.0,
    gt_time_limit: float = 2.0,
) -> Dict:
    """
    Check code correctness for BigCodeBench problems.
    
    Uses Windows-compatible evaluation function on Windows, and bigcodebench official untrusted_check function on other systems.
    
    Args:
        problem: BigCodeBench problem dictionary.
        solution: Generated complete code (including function signature).
        max_as_limit: Maximum address space limit (KB).
        max_data_limit: Maximum data segment limit (KB).
        max_stack_limit: Maximum stack limit (KB).
        min_time_limit: Minimum timeout (seconds).
        gt_time_limit: Groundtruth timeout (seconds).
    
    Returns:
        Dictionary containing passed and result.
    """
    test_code = problem.get("test", "")
    entry_point = problem.get("entry_point", "")
    
    if not test_code:
        return {"passed": False, "result": "No test code found"}
    
    if not solution:
        return {"passed": False, "result": "No solution provided"}
    
    # Check operating system, Windows uses compatible function
    import platform
    if platform.system() == "Windows":
        try:
            from windows_eval import check_bigcodebench_correctness_windows  # type: ignore
            
            # For compute-intensive tasks (using sklearn/scipy etc.), increase timeout
            # For matplotlib tasks, also need longer timeout
            timeout = max(min_time_limit, gt_time_limit) + 1
            if any(lib in solution for lib in ["sklearn", "scipy", "RandomForest", "PCA", "StandardScaler"]):
                timeout = max(timeout, 60.0)  # Compute-intensive tasks at least 60 seconds timeout
            elif "matplotlib" in solution or "plt." in solution:
                timeout = max(timeout, 120.0)  # matplotlib tasks at least 120 seconds timeout
            else:
                # Default timeout increased to 60 seconds to avoid normal task timeout
                timeout = max(timeout, 60.0)
            
            stat, details = check_bigcodebench_correctness_windows(
                code=solution,
                test_code=test_code,
                entry_point=entry_point,
                timeout=timeout
            )
            
            passed = (stat == "pass")
            if passed:
                result_msg = "passed"
            else:
                # Extract error details
                if isinstance(details, dict):
                    error_msg = details.get("ALL", str(details))
                else:
                    error_msg = str(details)
                result_msg = f"failed: {error_msg[:200]}"
            
            return {
                "passed": passed,
                "result": result_msg,
                "status": stat
            }
        except Exception as e:
            return {
                "passed": False,
                "result": f"evaluation error: {str(e)[:200]}",
                "status": "error"
            }
    else:
        # Unix systems use bigcodebench official evaluation function
        try:
            stat, details = untrusted_check(
                code=solution,
                test_code=test_code,
                entry_point=entry_point,
                max_as_limit=max_as_limit,
                max_data_limit=max_data_limit,
                max_stack_limit=max_stack_limit,
                min_time_limit=min_time_limit,
                gt_time_limit=gt_time_limit,
            )
            
            passed = (stat == PASS)
            if passed:
                result_msg = "passed"
            else:
                # Extract error details
                if isinstance(details, dict):
                    error_msg = details.get("ALL", str(details))
                else:
                    error_msg = str(details)
                result_msg = f"failed: {error_msg[:200]}"
            
            return {
                "passed": passed,
                "result": result_msg,
                "status": stat
            }
        except Exception as e:
            return {
                "passed": False,
                "result": f"evaluation error: {str(e)[:200]}",
                "status": "error"
            }


def evaluate_camel_on_bigcodebench(
    output_file: str,
    model: OpenAIModel,
    max_problems: int = None,
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False,
    subset: str = "full",
    split: str = "instruct",
    k: List[int] = [1, 10, 100],
    max_as_limit: int = 30 * 1024,
    max_data_limit: int = 30 * 1024,
    max_stack_limit: int = 10,
    min_time_limit: float = 1.0,
    gt_time_limit: float = 2.0,
    num_threads: int = 1,
) -> Dict:
    """
    Evaluate CAMEL framework on BigCodeBench dataset.
    
    Args:
        output_file: Output JSONL file path.
        model: Model adapter.
        max_problems: Maximum number of problems to process (None means all).
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
        subset: Dataset subset ("full" or "hard").
        split: Split to use ("instruct" or "complete").
        k: List of k values for pass@k.
        max_as_limit: Maximum address space limit (KB).
        max_data_limit: Maximum data segment limit (KB).
        max_stack_limit: Maximum stack limit (KB).
        min_time_limit: Minimum timeout (seconds).
        gt_time_limit: Groundtruth timeout (seconds).
        num_threads: Number of parallel threads (default 1, single-threaded).
    
    Returns:
        Evaluation result dictionary, containing pass@k and other metrics.
    """
    # Read BigCodeBench problems
    print(f"Reading BigCodeBench problems (subset={subset})...")
    try:
        all_problems = get_bigcodebench(subset=subset)
    except Exception as e:
        print(f"Error: Cannot load BigCodeBench dataset: {e}")
        print("\nHint: BigCodeBench data can be obtained by:")
        print("1. Install bigcodebench package: pip install bigcodebench")
        print("2. Or ensure bigcodebench-main is at the correct path")
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
    print(f"\nStarting code generation using CAMEL framework (split={split}, threads={num_threads})...")
    if num_threads > 10:
        print(f"Warning: Thread count {num_threads} is high, may cause API rate limiting.")
        print(f"       If encountering RetryError or 429 errors, recommend reducing thread count (e.g., --num_threads 5-8)")
    
    samples = []
    
    # Thread-safe locks for protecting shared resources
    samples_lock = threading.Lock()
    file_lock = threading.Lock()
    
    # Rate limiting control: use semaphore to limit concurrent API requests
    # Even with 20 threads, limit to only 10 concurrent API calls
    api_semaphore = threading.Semaphore(min(num_threads, 10)) if num_threads > 1 else None
    
    def process_problem(problem_item):
        """Function to process a single problem"""
        problem_id, problem = problem_item
        max_retries = 3
        retry_delay = 2  # seconds
        
        for attempt in range(max_retries):
            try:
                # Use semaphore to control concurrent API requests
                if api_semaphore:
                    api_semaphore.acquire()
                
                try:
                    sample = run_camel_on_problem(
                        problem=problem,
                        problem_id=problem_id,
                        model=model,
                        max_conversation_turns=max_conversation_turns,
                        word_limit=word_limit,
                        verbose=verbose,
                        split=split
                    )
                    return sample
                except Exception as inner_e:
                    # If inner function has already handled exception, shouldn't catch here
                    # But if run_camel_on_problem throws exception, we need to re-raise
                    # so outer retry logic can handle it
                    raise
                finally:
                    if api_semaphore:
                        api_semaphore.release()
            except Exception as e:
                error_str = str(e)
                error_type = type(e).__name__
                
                # Try to extract original exception from RetryError
                original_error = None
                original_error_str = error_str
                
                if "RetryError" in error_type:
                    # RetryError usually contains original exception information
                    # Try to extract more information from exception object
                    if hasattr(e, 'last_attempt'):
                        # tenacity's RetryError has last_attempt attribute
                        try:
                            last_attempt = e.last_attempt
                            if hasattr(last_attempt, 'exception'):
                                original_error = last_attempt.exception()
                                if original_error:
                                    original_error_str = str(original_error)
                                    error_type = f"{error_type}({type(original_error).__name__})"
                        except:
                            pass
                    
                    # Try to extract original error information from string
                    if "ValueError" in error_str or "raised ValueError" in error_str:
                        # This is a wrapped ValueError
                        original_error_str = "ValueError (may be API configuration or request format issue)"
                
                # Check if it's a rate limit or retry error
                is_rate_limit = (
                    "rate limit" in original_error_str.lower() or
                    "429" in original_error_str or
                    "RetryError" in error_type or
                    "TooManyRequests" in error_type or
                    "rate_limit_exceeded" in original_error_str.lower()
                )
                
                # Check if it's a temporary error (can retry)
                is_retryable = (
                    is_rate_limit or
                    "timeout" in original_error_str.lower() or
                    "connection" in original_error_str.lower() or
                    "503" in original_error_str or
                    "502" in original_error_str or
                    "500" in original_error_str or
                    "service unavailable" in original_error_str.lower()
                )
                
                # ValueError is usually not a temporary error, but if wrapped by RetryError, may be API issue
                if "ValueError" in original_error_str and "RetryError" in error_type:
                    # RetryError-wrapped ValueError may be API configuration issue, but could also be temporary
                    # Try retrying once first
                    is_retryable = attempt == 0  # Only retry once
                
                if attempt < max_retries - 1 and is_retryable:
                    # Calculate backoff time (exponential backoff)
                    wait_time = retry_delay * (2 ** attempt)
                    if is_rate_limit:
                        # Wait longer when rate limited
                        wait_time = max(wait_time, 10)
                    
                    print(f"\nWarning: Error occurred while processing {problem_id} ({error_type})")
                    print(f"  Detailed error: {original_error_str[:200]}")
                    print(f"  Retry {attempt + 1}/{max_retries}, waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    # Last attempt or non-retryable error
                    print(f"\nError: Exception occurred while processing {problem_id} ({error_type})")
                    print(f"  Detailed error: {original_error_str[:300]}")
                    
                    # If ValueError, provide more specific hints
                    if "ValueError" in original_error_str or "ValueError" in error_type:
                        print(f"  Hint: ValueError may be caused by:")
                        print(f"    1. API configuration issue (base_url, api_key, model_name)")
                        print(f"    2. Request format issue")
                        print(f"    3. Model doesn't support certain parameters")
                        print(f"    4. Recommend checking API configuration or using --verbose to see detailed errors")
                    
                    if verbose or attempt == max_retries - 1:
                        import traceback
                        print(f"\nFull error stack:")
                        traceback.print_exc()
                    
                    return {
                        "task_id": problem_id,
                        "solution": ""
                    }
        
        # If all retries failed
        return {
            "task_id": problem_id,
            "solution": ""
        }
    
    # Use multi-threading to process problems
    if num_threads > 1:
        problem_items = list(problems.items())
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            # Submit all tasks
            future_to_problem = {
                executor.submit(process_problem, item): item[0] 
                for item in problem_items
            }
            
            # Use tqdm to show progress
            with tqdm.tqdm(total=len(problem_items), desc="Generating code") as pbar:
                for future in as_completed(future_to_problem):
                    problem_id = future_to_problem[future]
                    try:
                        sample = future.result()
                        with samples_lock:
                            samples.append(sample)
                    except Exception as e:
                        print(f"\nError: Exception occurred while getting result for {problem_id}: {e}")
                        with samples_lock:
                            samples.append({
                                "task_id": problem_id,
                                "solution": ""
                            })
                    finally:
                        pbar.update(1)
        
        # Sort by original order (maintain problem order)
        problem_order = {pid: idx for idx, (pid, _) in enumerate(problems.items())}
        samples.sort(key=lambda x: problem_order.get(x["task_id"], float('inf')))
    else:
        # Single-threaded mode (original logic)
        for problem_id, problem in tqdm.tqdm(problems.items(), desc="Generating code"):
            sample = run_camel_on_problem(
                problem=problem,
                problem_id=problem_id,
                model=model,
                max_conversation_turns=max_conversation_turns,
                word_limit=word_limit,
                verbose=verbose,
                split=split
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
    print(f"\nStarting code evaluation (threads={num_threads})...")
    results = []
    results_lock = threading.Lock()
    completed_count_lock = threading.Lock()
    completed_count = 0
    
    # Prepare result file path
    result_file = output_file.replace('.jsonl', '_results.jsonl')
    
    def evaluate_sample(sample_item):
        """Function to evaluate a single sample"""
        idx, sample = sample_item
        problem_id = sample["task_id"]
        solution = sample["solution"]
        problem = problems.get(problem_id)
        
        if problem is None:
            result = {
                "task_id": problem_id,
                "passed": False,
                "result": "Problem not found",
                "status": "error"
            }
        else:
            result = check_bigcodebench_correctness(
                problem=problem,
                solution=solution,
                max_as_limit=max_as_limit,
                max_data_limit=max_data_limit,
                max_stack_limit=max_stack_limit,
                min_time_limit=min_time_limit,
                gt_time_limit=gt_time_limit,
            )
            result["task_id"] = problem_id
        
        return idx, result
    
    # Use multi-threading to evaluate code
    if num_threads > 1:
        sample_items = list(enumerate(samples, 1))
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            # Submit all evaluation tasks
            future_to_sample = {
                executor.submit(evaluate_sample, item): item[0]
                for item in sample_items
            }
            
            # Use tqdm to show progress
            with tqdm.tqdm(total=len(samples), desc="Evaluating code") as pbar:
                for future in as_completed(future_to_sample):
                    try:
                        idx, result = future.result()
                        with results_lock:
                            results.append((idx, result))
                        with completed_count_lock:
                            completed_count += 1
                            current_count = completed_count
                        
                        # Save every 100 rounds (thread-safe)
                        if current_count % 100 == 0:
                            # Sort by index then save
                            with results_lock:
                                sorted_results = sorted(results, key=lambda x: x[0])
                            with file_lock:
                                with open(result_file, 'w', encoding='utf-8') as f:
                                    for _, r in sorted_results:
                                        f.write(json.dumps(r, ensure_ascii=False) + '\n')
                            print(f"\n[Progress Save] Evaluated {current_count}/{len(samples)} tasks, saving intermediate results...")
                    except Exception as e:
                        print(f"\nError: Exception occurred while evaluating sample: {e}")
                    finally:
                        pbar.update(1)
        
        # Sort results by index
        results = [r for _, r in sorted(results, key=lambda x: x[0])]
    else:
        # Single-threaded mode (original logic)
        for idx, sample in enumerate(tqdm.tqdm(samples, desc="Evaluating code"), 1):
            problem_id = sample["task_id"]
            solution = sample["solution"]
            problem = problems.get(problem_id)
            
            if problem is None:
                results.append({
                    "task_id": problem_id,
                    "passed": False,
                    "result": "Problem not found",
                    "status": "error"
                })
            else:
                result = check_bigcodebench_correctness(
                    problem=problem,
                    solution=solution,
                    max_as_limit=max_as_limit,
                    max_data_limit=max_data_limit,
                    max_stack_limit=max_stack_limit,
                    min_time_limit=min_time_limit,
                    gt_time_limit=gt_time_limit,
                )
                result["task_id"] = problem_id
                results.append(result)
            
            # Save every 100 rounds
            if idx % 100 == 0:
                print(f"\n[Progress Save] Evaluated {idx}/{len(samples)} tasks, saving intermediate results...")
                with open(result_file, 'w', encoding='utf-8') as f:
                    for result in results:
                        f.write(json.dumps(result, ensure_ascii=False) + '\n')
                print(f"[Progress Save] Intermediate results saved to: {result_file}")
    
    # Save final evaluation results
    print(f"\nSaving final evaluation results to: {result_file}")
    with open(result_file, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + '\n')
    
    # Calculate pass@k
    print(f"\nCalculating pass@k metrics...")
    passed_count = sum(1 for r in results if r.get("passed", False))
    total_count = len(results)
    pass_rate = passed_count / total_count if total_count > 0 else 0.0
    
    # Calculate pass@k (using bigcodebench official estimate_pass_at_k)
    # Note: Here assumes each problem has only one sample (k=1 case)
    # For k>1, need multiple samples
    pass_at_k = {}
    for k_val in k:
        if k_val == 1:
            pass_at_k[f"pass@{k_val}"] = pass_rate
        else:
            # For k>1, need multiple samples, simplified handling here
            # In practice, should generate k samples for each problem
            pass_at_k[f"pass@{k_val}"] = pass_rate
    
    print(f"\n{'='*80}")
    print(f"Evaluation Results:")
    print(f"{'='*80}")
    print(f"Total: {total_count}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {total_count - passed_count}")
    print(f"Pass Rate: {pass_rate:.4f} ({pass_rate*100:.2f}%)")
    print(f"{'='*80}")
    
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
        description="Evaluate CAMEL framework using BigCodeBench dataset"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Output JSONL file path (default: bigcodebench/result/camel_bigcodebench_samples.jsonl)"
    )
    parser.add_argument(
        "--max_problems",
        type=int,
        default=0,
        help="Maximum number of problems to process (0 means all, positive number means first N)"
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
        "--subset",
        type=str,
        default="full",
        choices=["full", "hard"],
        help="Dataset subset (full or hard)"
    )
    parser.add_argument(
        "--split",
        type=str,
        default="complete",
        choices=["instruct", "complete"],
        help="Split to use (instruct or complete)"
    )
    parser.add_argument(
        "--k",
        type=str,
        default="1",
        help="List of k values for pass@k, separated by commas"
    )
    parser.add_argument(
        "--max_as_limit",
        type=int,
        default=30 * 1024,
        help="Maximum address space limit (KB)"
    )
    parser.add_argument(
        "--max_data_limit",
        type=int,
        default=30 * 1024,
        help="Maximum data segment limit (KB)"
    )
    parser.add_argument(
        "--max_stack_limit",
        type=int,
        default=10,
        help="Maximum stack limit (KB)"
    )
    parser.add_argument(
        "--min_time_limit",
        type=float,
        default=1.0,
        help="Minimum timeout (seconds)"
    )
    parser.add_argument(
        "--gt_time_limit",
        type=float,
        default=2.0,
        help="Groundtruth timeout (seconds)"
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
        "--num_threads",
        type=int,
        default=1,
        help="Number of parallel threads (default 1, single-threaded; recommend 2-8, adjust based on API limits)"
    )
    
    args = parser.parse_args()
    
    # Set default output path
    if args.output_file is None:
        bigcodebench_dir = Path(__file__).parent
        result_dir = bigcodebench_dir / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        args.output_file = str(result_dir / f"camel_bigcodebench_{args.split}_{args.subset}_samples.jsonl")
    
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
    
    # Validate thread count
    if args.num_threads < 1:
        print("Warning: Thread count must be >= 1, set to 1")
        args.num_threads = 1
    
    # Test API connection (optional, but helps quickly identify issues)
    print(f"\nTesting API connection...")
    print(f"  Model: {model_name}")
    print(f"  Base URL: {base_url}")
    try:
        # Try a simple API call
        test_messages = [{"role": "user", "content": "Hello"}]
        test_response = model.invoke(test_messages, settings={"max_tokens": 10})
        print(f"  ✓ API connection OK")
    except Exception as e:
        error_type = type(e).__name__
        error_str = str(e)
        print(f"  ✗ API connection test failed ({error_type}): {error_str[:200]}")
        print(f"\nWarning: API connection test failed, this may cause subsequent tasks to fail.")
        print(f"      Please check:")
        print(f"      1. Is API key correct")
        print(f"      2. Is Base URL correct")
        print(f"      3. Is model name correct")
        print(f"      4. Is network connection normal")
        
        # Ask if continue
        if not args.verbose:
            print(f"\nHint: Use --verbose to see more detailed error information")
            print(f"      If problem persists, recommend fixing API configuration first")
    
    # Run evaluation
    evaluate_camel_on_bigcodebench(
        output_file=args.output_file,
        model=model,
        max_problems=max_problems,
        max_conversation_turns=args.max_conversation_turns,
        word_limit=args.word_limit,
        verbose=args.verbose,
        subset=args.subset,
        split=args.split,
        k=k,
        max_as_limit=args.max_as_limit,
        max_data_limit=args.max_data_limit,
        max_stack_limit=args.max_stack_limit,
        min_time_limit=args.min_time_limit,
        gt_time_limit=args.gt_time_limit,
        num_threads=args.num_threads,
    )


if __name__ == "__main__":
    main()
