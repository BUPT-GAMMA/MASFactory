"""Evaluate CAMEL framework using SRDD dataset.

This module provides functionality to evaluate the CAMEL role-playing framework
on the SRDD (Software Requirements Description Dataset) benchmark.
"""

import os
import sys
import json
import csv
import argparse
from pathlib import Path
from typing import Dict, List
import tqdm

# Add parent directory to path for importing CAMEL framework
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import CAMEL framework (from parent directory)
# Important: Add srdd directory to the front of sys.path before importing workflow
# This ensures workflow.py and conversation_loop.py import prompts from srdd/prompts.py (evaluation-specific version)
srdd_dir = str(Path(__file__).parent)
if srdd_dir not in sys.path or sys.path.index(srdd_dir) != 0:
    # If srdd_dir is not in sys.path or not at the front, insert it at the front
    if srdd_dir in sys.path:
        sys.path.remove(srdd_dir)
    sys.path.insert(0, srdd_dir)

from workflow import create_camel_role_playing_workflow  # type: ignore
from masfactory import OpenAIModel  # type: ignore

# Import local code extraction tool
from code_extractor import extract_completion_from_camel_result  # type: ignore


def read_srdd_problems(csv_file: str) -> Dict[str, Dict]:
    """
    Read SRDD dataset CSV file.
    
    Args:
        csv_file: CSV file path.
    
    Returns:
        Problem dictionary, key is software name, value is dictionary containing Name, Description, Category.
    """
    problems = {}
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get('Name', '').strip()
            description = row.get('Description', '').strip()
            category = row.get('Category', '').strip()
            
            if name and description:
                # Use Name as task_id
                task_id = name
                problems[task_id] = {
                    "task_id": task_id,
                    "name": name,
                    "description": description,
                    "category": category
                }
    
    return problems


def generate_task_prompt(problem: Dict) -> str:
    """
    Convert SRDD problem to CAMEL framework task description.
    
    Args:
        problem: SRDD problem dictionary, containing name, description, category, etc.
    
    Returns:
        Task description string.
    """
    name = problem.get("name", "")
    description = problem.get("description", "")
    category = problem.get("category", "")
    
    task_description = f"""Develop a complete Python software application based on the following requirements:

Software Name: {name}
Category: {category}
Description: {description}

REQUIREMENTS:
1. The software must be a complete, runnable Python application.
2. Include all necessary imports at the top of the file.
3. Implement all core features described in the requirements.
4. Include proper error handling where appropriate.
5. The code should be well-documented and user-friendly.
6. The software should be self-contained (does not require external data sources or internet access).
7. Include a main entry point (if __name__ == "__main__":) if the software needs to be executed directly.
8. Use proper Python coding standards and PEP 8 style guidelines.

The software should be ready to execute and fulfill all the requirements described above."""
    
    return task_description


def write_jsonl(file_path: str, data: List[Dict]):
    """
    Write data to JSONL file.
    
    Args:
        file_path: Output file path.
        data: List of data to write.
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


def stream_jsonl(file_path: str):
    """
    Stream read JSONL file.
    
    Args:
        file_path: JSONL file path.
    
    Yields:
        JSON object for each line.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def run_camel_on_problem(
    problem: Dict,
    model: OpenAIModel,
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False
) -> Dict:
    """
    Run CAMEL framework on a single SRDD problem.
    
    Args:
        problem: SRDD problem dictionary.
        model: Model adapter.
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
    
    Returns:
        Dictionary containing task_id, name, category, and completion.
    """
    task_id = problem["task_id"]
    task_prompt = generate_task_prompt(problem)
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"Processing problem: {task_id}")
        print(f"{'='*80}")
        print(f"Software name: {problem.get('name', '')}")
        print(f"Category: {problem.get('category', '')}")
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
        completion = extract_completion_from_camel_result(result)
        
        if verbose:
            print(f"\nExtracted code length: {len(completion)} characters")
            if completion:
                print(f"Code preview:\n{completion[:300]}...")
        
        return {
            "task_id": task_id,
            "name": problem.get("name", ""),
            "category": problem.get("category", ""),
            "description": problem.get("description", ""),
            "completion": completion
        }
    
    except Exception as e:
        print(f"\nError: Exception occurred while processing {task_id}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return {
            "task_id": task_id,
            "name": problem.get("name", ""),
            "category": problem.get("category", ""),
            "description": problem.get("description", ""),
            "completion": ""  # Return empty code
        }


def evaluate_camel_on_srdd(
    output_file: str,
    model: OpenAIModel,
    max_problems: int = None,
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False,
    csv_file: str = None,
) -> Dict:
    """
    Evaluate CAMEL framework on SRDD dataset.
    
    Args:
        output_file: Output JSONL file path.
        model: Model adapter.
        max_problems: Maximum number of problems to process (None means all).
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
        csv_file: SRDD CSV file path (None means use default path).
    
    Returns:
        Evaluation result dictionary, containing statistics.
    """
    # Read SRDD problems
    if csv_file is None:
        # Use default path
        default_path = Path(__file__).parent.parent.parent.parent.parent / "datasets" / "srdd" / "data" / "data_attribute_format.csv"
        if not default_path.exists():
            # Try other possible paths
            alternative_paths = [
                Path(__file__).parent.parent.parent.parent.parent.parent / "datasets" / "srdd" / "data" / "data_attribute_format.csv",
                Path(__file__).parent / "data_attribute_format.csv",
            ]
            for alt_path in alternative_paths:
                if alt_path.exists():
                    default_path = alt_path
                    break
        csv_file = str(default_path)
    
    print(f"Reading SRDD problem file: {csv_file}")
    all_problems = read_srdd_problems(csv_file)
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
    
    # Statistics
    total = len(samples)
    with_code = sum(1 for s in samples if s.get("completion", "").strip())
    empty_code = total - with_code
    
    stats = {
        "total_problems": total,
        "with_code": with_code,
        "empty_code": empty_code,
        "success_rate": with_code / total if total > 0 else 0.0
    }
    
    print(f"\n{'='*80}")
    print("Evaluation Results:")
    print(f"{'='*80}")
    print(f"Total problems: {stats['total_problems']}")
    print(f"Successfully generated code: {stats['with_code']}")
    print(f"Empty code: {stats['empty_code']}")
    print(f"Success rate: {stats['success_rate']:.4f}")
    print(f"{'='*80}")
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate CAMEL framework on SRDD dataset"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Output JSONL file path (default saved in srdd/result folder)"
    )
    parser.add_argument(
        "--max_problems",
        type=int,
        default=0,
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
        "--csv_file",
        type=str,
        default=None,
        help="SRDD CSV file path (default uses dataset path)"
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
        srdd_dir = Path(__file__).parent
        result_dir = srdd_dir / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        args.output_file = str(result_dir / "camel_srdd_samples.jsonl")
    
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
    
    # Handle max_problems: 0 or negative means all
    max_problems = None if args.max_problems <= 0 else args.max_problems
    
    # Run evaluation
    evaluate_camel_on_srdd(
        output_file=args.output_file,
        model=model,
        max_problems=max_problems,
        max_conversation_turns=args.max_conversation_turns,
        word_limit=args.word_limit,
        verbose=args.verbose,
        csv_file=args.csv_file,
    )


if __name__ == "__main__":
    main()

