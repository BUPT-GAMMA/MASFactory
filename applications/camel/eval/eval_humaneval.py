"""Evaluate CAMEL framework using HumanEval dataset.

This module provides functionality to evaluate the CAMEL role-playing framework
on the HumanEval code generation benchmark.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List
import tqdm

# Add parent directory to path for importing CAMEL framework
sys.path.insert(0, str(Path(__file__).parent.parent))

# Add human_eval module path
humaneval_path = Path(__file__).parent.parent.parent.parent.parent / "datasets" / "human-eval-master" / "human-eval-master"
if humaneval_path.exists():
    sys.path.insert(0, str(humaneval_path))
else:
    # Try other possible paths
    alternative_paths = [
        Path(__file__).parent.parent.parent.parent.parent.parent / "datasets" / "human-eval-master" / "human-eval-master",
        Path(__file__).parent / "human-eval-master",
    ]
    for alt_path in alternative_paths:
        if alt_path.exists():
            sys.path.insert(0, str(alt_path))
            break

# Import human_eval module (if available)
try:
    from human_eval.data import read_problems, write_jsonl, stream_jsonl  # type: ignore
    # Try to import Windows-compatible execution module
    import platform
    if platform.system() == "Windows":
        # Windows system: use compatible execution module
        from windows_execution import check_correctness  # type: ignore
        # Create Windows-compatible evaluation function
        from human_eval.evaluation import estimate_pass_at_k  # type: ignore
        from collections import defaultdict, Counter  # type: ignore
        from concurrent.futures import ThreadPoolExecutor, as_completed  # type: ignore
        import numpy as np  # type: ignore
        
        def evaluate_functional_correctness(
            sample_file: str,
            k: List[int] = [1, 10, 100],
            n_workers: int = 4,
            timeout: float = 3.0,
            problem_file: str = None,
        ):
            """Windows-compatible evaluation function."""
            problems = read_problems(problem_file)
            
            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                futures = []
                completion_id = Counter()
                n_samples = 0
                results = defaultdict(list)
                
                print("Reading samples...")
                for sample in tqdm.tqdm(stream_jsonl(sample_file)):
                    task_id = sample["task_id"]
                    completion = sample["completion"]
                    args = (problems[task_id], completion, timeout, completion_id[task_id])
                    future = executor.submit(check_correctness, *args)
                    futures.append(future)
                    completion_id[task_id] += 1
                    n_samples += 1
                
                assert len(completion_id) == len(problems), "Some problems are not attempted."
                
                print("Running test suites...")
                for future in tqdm.tqdm(as_completed(futures), total=len(futures)):
                    result = future.result()
                    results[result["task_id"]].append((result["completion_id"], result))
            
            # Calculate pass@k.
            total, correct = [], []
            for result in results.values():
                result.sort()
                passed = [r[1]["passed"] for r in result]
                total.append(len(passed))
                correct.append(sum(passed))
            total = np.array(total)
            correct = np.array(correct)
            
            ks = k
            pass_at_k = {f"pass@{k}": estimate_pass_at_k(total, correct, k).mean()
                         for k in ks if (total >= k).all()}
            
            # Finally, save the results in one file:
            def combine_results():
                for sample in stream_jsonl(sample_file):
                    task_id = sample["task_id"]
                    result = results[task_id].pop(0)
                    sample["result"] = result[1]["result"]
                    sample["passed"] = result[1]["passed"]
                    yield sample
            
            out_file = sample_file + "_results.jsonl"
            print(f"Writing results to {out_file}...")
            write_jsonl(out_file, tqdm.tqdm(combine_results(), total=n_samples))
            
            return pass_at_k
        
        print("Using Windows-compatible evaluation module")
    else:
        # Unix system: use original module
        from human_eval.evaluation import evaluate_functional_correctness  # type: ignore
except ImportError as e:
    print(f"Warning: Cannot import human_eval module: {e}")
    print(f"Please ensure HumanEval dataset is at the correct path, or use --problem_file parameter to specify path")
    # Define placeholder functions to avoid runtime errors
    def read_problems(*args, **kwargs):
        raise ImportError("human_eval module not found, please check dataset path")
    def write_jsonl(*args, **kwargs):
        raise ImportError("human_eval module not found, please check dataset path")
    def stream_jsonl(*args, **kwargs):
        raise ImportError("human_eval module not found, please check dataset path")
    def evaluate_functional_correctness(*args, **kwargs):
        raise ImportError("human_eval module not found, please check dataset path")

# Import CAMEL framework (from parent directory)
# Important: Add eval directory to the front of sys.path before importing workflow
# This ensures workflow.py and conversation_loop.py will prioritize using eval/prompts.py (evaluation-specific version)
eval_dir = str(Path(__file__).parent)
if eval_dir not in sys.path or sys.path.index(eval_dir) != 0:
    # If eval_dir is not in sys.path, or not at the front, insert to front
    if eval_dir in sys.path:
        sys.path.remove(eval_dir)
    sys.path.insert(0, eval_dir)

from workflow import create_camel_role_playing_workflow  # type: ignore
from masfactory import OpenAIModel  # type: ignore

# Import local code extraction tool
from code_extractor import extract_completion_from_camel_result  # type: ignore


def generate_task_prompt(problem: Dict) -> str:
    """Convert HumanEval problem to CAMEL framework task description.
    
    Args:
        problem: HumanEval problem dictionary containing prompt, test, etc.
    
    Returns:
        Task description string.
    """
    prompt = problem.get("prompt", "")
    entry_point = problem.get("entry_point", "")
    
    # Extract parameter names from function signature for emphasis
    import re
    sig_match = re.search(rf'def {re.escape(entry_point)}\(([^)]+)\)', prompt)
    param_names = []
    if sig_match:
        params_str = sig_match.group(1)
        param_names = [p.strip().split(':')[0].strip() for p in params_str.split(',')]
    
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
1. Use EXACTLY the parameter names specified in the function signature above. Do NOT rename them (e.g., if signature says "string", use "string", NOT "s" or "input_string").
2. If your code uses standard library modules (like math, re, collections, etc.), you can use them directly. The evaluation environment typically has standard libraries imported. However, if you want to be explicit, you can include import statements at the module level.
3. If you need helper functions (like is_prime(), generate_primes(), etc.), you MUST define them INSIDE the main function as nested functions. Do NOT define them outside the main function.
4. The code must be complete, syntactically correct, and ready to execute.
5. Use 4-space indentation for all code.
6. Do NOT include docstrings in the function body.
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
    Run CAMEL framework on a single HumanEval problem.
    
    Args:
        problem: HumanEval problem dictionary.
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
        entry_point = problem.get("entry_point")
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


def evaluate_camel_on_humaneval(
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
    Evaluate CAMEL framework on HumanEval dataset.
    
    Args:
        output_file: Output JSONL file path.
        model: Model adapter.
        max_problems: Maximum number of problems to process (None means all).
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
        problem_file: HumanEval problem file path (None means use default path).
        k: List of k values for pass@k.
        n_workers: Number of parallel worker threads for evaluation.
        timeout: Timeout for each test (seconds).
    
    Returns:
        Evaluation result dictionary, containing pass@k and other metrics.
    """
    # Read HumanEval problems
    if problem_file is None:
        # Use default path
        default_path = Path(__file__).parent.parent.parent.parent.parent / "datasets" / "human-eval-master" / "human-eval-master" / "data" / "HumanEval.jsonl.gz"
        if not default_path.exists():
            # Try other possible paths
            humaneval_path = Path(__file__).parent.parent.parent.parent.parent / "datasets" / "human-eval-master" / "human-eval-master"
            default_path = humaneval_path / "data" / "HumanEval.jsonl.gz"
        problem_file = str(default_path)
    
    print(f"Reading HumanEval problem file: {problem_file}")
    all_problems = read_problems(problem_file)
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
    
    for task_id, problem in tqdm.tqdm(problems.items(), desc="Generating code"):
        sample = run_camel_on_problem(
            problem=problem,
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
    write_jsonl(output_file, samples)
    
    # Evaluation: if limited number of problems, need to create temporary problem file
    print(f"\nStarting evaluation...")
    if max_problems is not None and max_problems > 0:
        # Create temporary problem file, only containing problems we tested
        import tempfile
        import gzip
        temp_problem_file = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
        for task_id in problems.keys():
            problem_data = all_problems[task_id]
            temp_problem_file.write(json.dumps(problem_data) + '\n')
        temp_problem_file.close()
        eval_problem_file = temp_problem_file.name
    else:
        eval_problem_file = problem_file
    
    try:
        pass_at_k = evaluate_functional_correctness(
            sample_file=output_file,
            k=k,
            n_workers=n_workers,
            timeout=timeout,
            problem_file=eval_problem_file
        )
    finally:
        # Clean up temporary file
        if max_problems is not None and max_problems > 0:
            try:
                os.unlink(eval_problem_file)
            except:
                pass
    
    print(f"\n{'='*80}")
    print("Evaluation Results:")
    print(f"{'='*80}")
    for metric, value in pass_at_k.items():
        print(f"{metric}: {value:.4f}")
    print(f"{'='*80}")
    
    return pass_at_k


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate CAMEL framework using HumanEval dataset"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Output JSONL file path (default saved in eval/result folder)"
    )
    parser.add_argument(
        "--max_problems",
        type=int,
        default=10,
        help="Maximum number of problems to process (for testing, 0 or negative means all, default 0 means all)"
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
        help="HumanEval problem file path (default uses dataset path)"
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
    
    args = parser.parse_args()
    
    # Set default output path (based on script directory)
    if args.output_file is None:
        eval_dir = Path(__file__).parent
        result_dir = eval_dir / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        args.output_file = str(result_dir / "camel_humaneval_samples.jsonl")
    
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
    evaluate_camel_on_humaneval(
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

