"""Evaluate CAMEL framework using CommonGen dataset.

This module provides functionality to evaluate the CAMEL role-playing framework
on the CommonGen (Common Sense Generation) benchmark.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional
import tqdm

# Add parent directory to path for importing CAMEL framework
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import CAMEL framework (from parent directory)
# Important: Add commongen directory to the front of sys.path before importing workflow
# This ensures workflow.py and conversation_loop.py import prompts from commongen/prompts.py (CommonGen-specific version)
commongen_dir = str(Path(__file__).parent)
if commongen_dir not in sys.path or sys.path.index(commongen_dir) != 0:
    if commongen_dir in sys.path:
        sys.path.remove(commongen_dir)
    sys.path.insert(0, commongen_dir)

# Then add eval directory (as fallback)
eval_dir = str(Path(__file__).parent.parent / "eval")
if eval_dir not in sys.path:
    sys.path.insert(1, eval_dir)

from workflow import create_camel_role_playing_workflow  # type: ignore
from masfactory import OpenAIModel  # type: ignore

# Import local modules
from prompts import COMMONGEN_TASK_TEMPLATE  # type: ignore
from text_extractor import extract_sentence_from_camel_result  # type: ignore


def load_commongen_data(src_file: str, tgt_file: Optional[str] = None) -> List[Dict]:
    """
    Load CommonGen dataset.
    
    Args:
        src_file: Source file path (containing concept lists, space-separated per line).
        tgt_file: Target file path (optional, containing reference sentences).
    
    Returns:
        List of problems, each element contains concepts and optional reference.
    """
    problems = []
    
    # Read source file (concept lists)
    with open(src_file, 'r', encoding='utf-8') as f:
        src_lines = [line.strip() for line in f if line.strip()]
    
    # Read target file (reference sentences, if provided)
    tgt_lines = []
    if tgt_file and os.path.exists(tgt_file):
        with open(tgt_file, 'r', encoding='utf-8') as f:
            tgt_lines = [line.strip() for line in f if line.strip()]
    
    # Combine data
    for idx, src_line in enumerate(src_lines):
        concepts = src_line.split()  # Concept list (space-separated)
        problem = {
            "task_id": idx,
            "concepts": concepts,
            "concepts_str": src_line,  # Original string form
        }
        
        # If there's a reference sentence, add it
        if idx < len(tgt_lines):
            problem["reference"] = tgt_lines[idx]
        
        problems.append(problem)
    
    return problems


def generate_task_prompt(problem: Dict) -> str:
    """
    Convert CommonGen problem to CAMEL framework task description.
    
    Args:
        problem: CommonGen problem dictionary, containing concepts or concepts_str.
    
    Returns:
        Task description string.
    """
    concepts_str = problem.get("concepts_str", "")
    if not concepts_str:
        # If no concepts_str, build from concepts list
        concepts = problem.get("concepts", [])
        concepts_str = " ".join(concepts)
    
    task_description = COMMONGEN_TASK_TEMPLATE.format(concepts=concepts_str)
    return task_description


def run_camel_on_problem(
    problem: Dict,
    model: OpenAIModel,
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False
) -> Dict:
    """
    Run CAMEL framework on a single CommonGen problem.
    
    Args:
        problem: CommonGen problem dictionary.
        model: Model adapter.
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
    
    Returns:
        Dictionary containing task_id and generated_sentence.
    """
    task_id = problem["task_id"]
    task_prompt = generate_task_prompt(problem)
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"Processing problem: {task_id}")
        print(f"{'='*80}")
        print(f"Concepts: {problem.get('concepts_str', '')}")
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
        
        # Extract generated sentence
        generated_sentence = extract_sentence_from_camel_result(result)
        
        if verbose:
            print(f"\nGenerated sentence: {generated_sentence}")
            if "reference" in problem:
                print(f"Reference sentence: {problem['reference']}")
        
        return {
            "task_id": task_id,
            "concepts": problem.get("concepts", []),
            "concepts_str": problem.get("concepts_str", ""),
            "generated_sentence": generated_sentence,
            "reference": problem.get("reference", ""),
        }
    
    except Exception as e:
        print(f"\nError: Exception occurred while processing {task_id}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return {
            "task_id": task_id,
            "concepts": problem.get("concepts", []),
            "concepts_str": problem.get("concepts_str", ""),
            "generated_sentence": "",  # Return empty sentence
            "reference": problem.get("reference", ""),
        }


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Evaluate CommonGen dataset using CAMEL framework")
    
    # Set default data file paths (prioritize dataset directory, if not exists use test_data)
    dataset_dir = Path(__file__).parent / "dataset"
    test_data_dir = Path(__file__).parent / "test_data"
    
    # Prioritize using dev set in dataset directory
    default_src_file = str(dataset_dir / "commongen.dev.src_alpha.txt")
    default_tgt_file = str(dataset_dir / "commongen.dev.tgt.txt")
    
    # If dataset directory doesn't exist or file doesn't exist, use test_data
    if not os.path.exists(default_src_file):
        default_src_file = str(test_data_dir / "test.src_alpha.txt")
        default_tgt_file = str(test_data_dir / "test.tgt.txt")
    
    parser.add_argument(
        "--src_file",
        type=str,
        default=default_src_file,
        help=f"CommonGen source file path (containing concept lists, space-separated per line, default: {default_src_file})"
    )
    parser.add_argument(
        "--tgt_file",
        type=str,
        default=default_tgt_file if os.path.exists(default_tgt_file) else None,
        help=f"CommonGen target file path (optional, containing reference sentences, default: {default_tgt_file})"
    )
    parser.add_argument(
        "--split",
        type=str,
        choices=["train", "dev", "test"],
        default="dev",
        help="Dataset split to use (train/dev/test, default: dev)"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Output JSONL file path (default: commongen/result/camel_commongen_samples.jsonl)"
    )
    parser.add_argument(
        "--max_problems",
        type=int,
        default=0,
        help="Maximum number of problems to process (0 means all, positive means first N, default 10)"
    )
    parser.add_argument(
        "--max_conversation_turns",
        type=int,
        default=40,
        help="Maximum number of conversation turns (default 40)"
    )
    parser.add_argument(
        "--word_limit",
        type=int,
        default=50,
        help="Word limit for task specification (default 50)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed information"
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
    
    # If user specified split but not src_file, automatically load corresponding split data from dataset directory
    # Check if using default path (indicates user didn't manually specify src_file)
    current_default_src = str(dataset_dir / "commongen.dev.src_alpha.txt")
    if not os.path.exists(current_default_src):
        current_default_src = str(test_data_dir / "test.src_alpha.txt")
    
    if args.src_file == current_default_src:
        # User using default path, automatically select corresponding data file based on split parameter
        split_src_file = dataset_dir / f"commongen.{args.split}.src_alpha.txt"
        split_tgt_file = dataset_dir / f"commongen.{args.split}.tgt.txt"
        
        if os.path.exists(split_src_file):
            args.src_file = str(split_src_file)
            if os.path.exists(split_tgt_file):
                args.tgt_file = str(split_tgt_file)
            else:
                args.tgt_file = None
            print(f"Automatically loading {args.split} dataset from dataset directory")
    
    # Set output file path
    if args.output_file is None:
        output_dir = Path(__file__).parent / "result"
        output_dir.mkdir(exist_ok=True)
        # Set output filename based on split
        output_file = output_dir / f"camel_commongen_{args.split}_samples.jsonl"
    else:
        output_file = Path(args.output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Check if source file exists
    if not os.path.exists(args.src_file):
        print(f"Error: Source file does not exist: {args.src_file}")
        print(f"\nHint: If using --split parameter, ensure corresponding data file exists in dataset directory")
        print(f"Example: dataset/commongen.{args.split}.src_alpha.txt")
        return
    
    # Load data
    print(f"Loading CommonGen data from: {args.src_file}")
    problems = load_commongen_data(args.src_file, args.tgt_file)
    print(f"Loaded {len(problems)} problems")
    
    # Limit number of problems
    if args.max_problems > 0:
        problems = problems[:args.max_problems]
        print(f"Limited to first {len(problems)} problems")
    
    # Create model adapter
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    base_url = args.base_url or os.getenv("OPENAI_BASE_URL", "https://api.csun.site/v1/")
    model_name = args.model_name or os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
    
    if not api_key:
        print("\nError: Please set OPENAI_API_KEY environment variable or use --api_key parameter")
        return
    
    model = OpenAIModel(api_key=api_key, base_url=base_url, model_name=model_name)
    
    # Process each problem
    print(f"\nStarting to process {len(problems)} problems...")
    print(f"Auto-saving every 100 problems to: {output_file}")
    
    # Check if there are existing partial results (for resuming)
    existing_results = {}
    if output_file.exists():
        print(f"Detected existing result file, reading processed problems...")
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        existing_result = json.loads(line)
                        task_id = existing_result.get("task_id")
                        if task_id is not None:
                            existing_results[task_id] = existing_result
            if existing_results:
                print(f"Found {len(existing_results)} processed problems, will skip these")
        except Exception as e:
            print(f"Warning: Failed to read existing result file: {e}, will start fresh")
            existing_results = {}
    
    # Process each problem
    save_interval = 100  # Save every 100 problems
    processed_count = 0
    skipped_count = 0
    new_results = []  # Store newly processed results
    
    for problem in tqdm.tqdm(problems, desc="Processing problems"):
        task_id = problem["task_id"]
        
        # If already processed, skip
        if task_id in existing_results:
            skipped_count += 1
            processed_count += 1
            continue
        
        # Process new problem
        result = run_camel_on_problem(
            problem=problem,
            model=model,
            max_conversation_turns=args.max_conversation_turns,
            word_limit=args.word_limit,
            verbose=args.verbose
        )
        new_results.append(result)
        processed_count += 1
        
        # Save every 100 problems
        if len(new_results) >= save_interval:
            print(f"\n[Auto-save] Processed {processed_count}/{len(problems)} problems, saving {len(new_results)} new results...")
            # Use append mode
            with open(output_file, 'a', encoding='utf-8') as f:
                for result_item in new_results:
                    f.write(json.dumps(result_item, ensure_ascii=False) + '\n')
            print(f"[Auto-save] Saved to: {output_file}")
            new_results = []  # Clear saved results
    
    # Save remaining results (if any)
    if new_results:
        print(f"\nSaving remaining {len(new_results)} results...")
        with open(output_file, 'a', encoding='utf-8') as f:
            for result_item in new_results:
                f.write(json.dumps(result_item, ensure_ascii=False) + '\n')
    
    # Read all results for statistics
    all_results = []
    if output_file.exists():
        with open(output_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    all_results.append(json.loads(line))
    
    # Final statistics
    print(f"\nComplete! Processed {processed_count} problems")
    if skipped_count > 0:
        print(f"  - Newly processed: {processed_count - skipped_count}")
        print(f"  - Skipped (already exist): {skipped_count}")
    print(f"Results saved to: {output_file}")
    print(f"Total result count: {len(all_results)}")
    
    # Statistics
    generated_count = sum(1 for r in all_results if r.get("generated_sentence", "").strip())
    print(f"Successfully generated sentences: {generated_count}/{len(all_results)}")


if __name__ == "__main__":
    main()

