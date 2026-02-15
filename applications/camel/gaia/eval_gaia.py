"""Evaluate CAMEL framework using GAIA dataset.

This module provides functionality to evaluate the CAMEL role-playing framework
on the GAIA (General AI Assistant) benchmark.
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

# Import CAMEL framework
from workflow import create_camel_role_playing_workflow  # type: ignore
from masfactory import OpenAIModel  # type: ignore

# Import local modules
gaia_dir = Path(__file__).parent
import importlib.util

# Import prompts module
prompts_spec = importlib.util.spec_from_file_location(
    "gaia_prompts",
    gaia_dir / "prompts.py"
)
gaia_prompts = importlib.util.module_from_spec(prompts_spec)
prompts_spec.loader.exec_module(gaia_prompts)
create_task_prompt = gaia_prompts.create_task_prompt

# Import answer_extractor module
answer_extractor_spec = importlib.util.spec_from_file_location(
    "gaia_answer_extractor",
    gaia_dir / "answer_extractor.py"
)
gaia_answer_extractor = importlib.util.module_from_spec(answer_extractor_spec)
answer_extractor_spec.loader.exec_module(gaia_answer_extractor)
extract_answer_from_camel_result = gaia_answer_extractor.extract_answer_from_camel_result
compare_answers = gaia_answer_extractor.compare_answers

# Import tools module
tools_spec = importlib.util.spec_from_file_location(
    "gaia_tools",
    gaia_dir / "tools.py"
)
gaia_tools = importlib.util.module_from_spec(tools_spec)
tools_spec.loader.exec_module(gaia_tools)

# Get all tool functions
GAIA_TOOLS = [
    gaia_tools.read_file,
    gaia_tools.read_csv,
    gaia_tools.read_json,
    gaia_tools.calculate,
    gaia_tools.list_files,
    gaia_tools.search_in_file,
    gaia_tools.get_file_info,
]


def load_gaia_examples(
    data_dir: str = None,
    split: str = "test",
    use_huggingface: bool = True,
    max_examples: Optional[int] = None
) -> List[Dict]:
    """
    Load GAIA dataset from Hugging Face or local files.
    
    Args:
        data_dir: Data directory path (if None, try to load from datasets folder).
        split: Dataset split ("test" or "validation").
        use_huggingface: Whether to prioritize loading from Hugging Face.
        max_examples: Maximum number of tasks to load (None means all).
    
    Returns:
        List of tasks, each task is a dictionary.
    """
    examples = []
    
    # Prioritize loading from Hugging Face
    if use_huggingface:
        try:
            print("Attempting to load GAIA dataset from Hugging Face...")
            from datasets import load_dataset
            from huggingface_hub import login
            
            # Try to use Hugging Face token
            hf_token = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")
            if hf_token:
                try:
                    login(token=hf_token)
                    print("Logged in using Hugging Face token")
                except Exception as login_error:
                    print(f"Warning: Hugging Face login failed: {login_error}")
                    print("Will try to load directly (if already logged in)...")
            
            try:
                dataset = load_dataset("cmriat/gaia", token=hf_token)
                print(f"Successfully loaded GAIA dataset from Hugging Face")
                
                # Select split
                if split in dataset:
                    split_data = dataset[split]
                elif "test" in dataset:
                    split_data = dataset["test"]
                    print(f"Warning: {split} split not found, using test split")
                else:
                    # Take first split
                    split_name = list(dataset.keys())[0]
                    split_data = dataset[split_name]
                    print(f"Warning: Using first available split: {split_name}")
                
                # Convert to list
                examples = [item for item in split_data]
                print(f"Loaded {len(examples)} tasks")
                
            except Exception as load_error:
                if "gated" in str(load_error).lower() or "authenticated" in str(load_error).lower():
                    print("Hint: GAIA dataset may require Hugging Face authentication.")
                    print("Please follow these steps:")
                    print("1. Visit https://huggingface.co/datasets/cmriat/gaia to request access")
                    print("2. Get Hugging Face token: https://huggingface.co/settings/tokens")
                    print("3. Set environment variable: set HUGGINGFACE_TOKEN=your_token_here")
                    print("   Or run: huggingface-cli login")
                    print("Will try to load from local files...")
                else:
                    print(f"Failed to load from Hugging Face: {load_error}")
                    print("Will try to load from local files...")
                    
        except ImportError as import_error:
            print("Warning: datasets library not installed, cannot load from Hugging Face.")
            print("Please run: pip install datasets huggingface_hub")
            print("Will try to load from local files...")
        except Exception as e:
            print(f"Failed to load from Hugging Face: {e}")
            print("Will try to load from local files...")
    
    # If Hugging Face loading failed, try loading from local files
    if not examples:
        if data_dir is None:
            # Try multiple possible paths
            base_path = Path(__file__).parent.parent.parent.parent.parent.parent
            possible_paths = [
                base_path / "datasets" / "gaia",
                base_path / "datasets" / "gaia-main",
            ]
        else:
            possible_paths = [Path(data_dir)]
        
        data_path = None
        for path in possible_paths:
            test_file = path / f"{split}.jsonl"
            if test_file.exists():
                data_path = test_file
                break
        
        if data_path is None:
            # Try to find any jsonl files
            for path in possible_paths:
                if path.exists():
                    jsonl_files = list(path.glob("*.jsonl"))
                    if jsonl_files:
                        data_path = jsonl_files[0]
                        print(f"Found data file: {data_path}")
                        break
        
        if data_path is None:
            error_msg = f"Cannot find GAIA data file\n"
            error_msg += f"Tried paths: {[str(p) for p in possible_paths]}\n"
            error_msg += "\nSolutions:\n"
            error_msg += "1. Load from Hugging Face (recommended):\n"
            error_msg += "   - Visit https://huggingface.co/datasets/cmriat/gaia to request access\n"
            error_msg += "   - Get token: https://huggingface.co/settings/tokens\n"
            error_msg += "   - Set environment variable: set HUGGINGFACE_TOKEN=your_token_here\n"
            error_msg += "   - Or run: huggingface-cli login\n"
            error_msg += "2. Load from local files:\n"
            error_msg += "   - Download GAIA dataset to datasets/gaia/ directory\n"
            error_msg += "   - Ensure test.jsonl or validation.jsonl file is included\n"
            raise FileNotFoundError(error_msg)
        
        print(f"Loading GAIA data from local file: {data_path}")
        with open(data_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        item = json.loads(line)
                        examples.append(item)
                    except json.JSONDecodeError as e:
                        print(f"Warning: Skipping invalid JSON line: {e}")
        
        print(f"Loaded {len(examples)} tasks")
    
    # Limit number of tasks
    if max_examples is not None and max_examples > 0:
        examples = examples[:max_examples]
        print(f"Limited to first {max_examples} tasks")
    
    return examples


def load_file_content(file_path: str) -> Optional[str]:
    """
    Load file content.
    
    Args:
        file_path: File path.
    
    Returns:
        File content, or None if reading fails.
    """
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
    except Exception as e:
        print(f"Warning: Cannot read file {file_path}: {e}")
    return None


def run_camel_on_task(
    task: Dict,
    task_id: str,
    model: OpenAIModel,
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False,
    data_dir: Optional[str] = None
) -> Dict:
    """
    Run CAMEL framework on a single GAIA task.
    
    Args:
        task: GAIA task dictionary.
        task_id: Task ID.
        model: Model adapter.
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
        data_dir: Data directory path (for finding attachment files).
    
    Returns:
        Dictionary containing task_id, predicted_answer, correct_answer, etc.
    """
    # Extract task information
    # GAIA dataset may have field name variants
    question = task.get("Question", task.get("question", task.get("task", "")))
    
    # File name field may have multiple variants
    file_names = task.get("file_name", task.get("file_names", task.get("files", [])))
    if isinstance(file_names, str):
        file_names = [file_names] if file_names else []
    elif not isinstance(file_names, list):
        file_names = []
    # Filter empty strings
    file_names = [f for f in file_names if f]
    
    # Correct answer field may have multiple variants (GAIA dataset may not contain correct answer, need to get from other sources)
    correct_answer = task.get("Answer", task.get("answer", task.get("Final answer", 
        task.get("correct_answer", task.get("solution", task.get("ground_truth", ""))))))
    
    # Try to load attachment file contents
    file_contents = {}
    if file_names and data_dir:
        data_path = Path(data_dir)
        for file_name in file_names:
            # Try multiple possible paths
            possible_paths = [
                data_path / file_name,
                data_path / "files" / file_name,
                data_path / "attachments" / file_name,
            ]
            for file_path in possible_paths:
                content = load_file_content(str(file_path))
                if content:
                    file_contents[file_name] = content
                    break
    
    # Set to use GAIA-specific prompts
    import os
    os.environ["USE_GAIA_PROMPTS"] = "true"
    
    # Generate task prompt
    task_prompt = create_task_prompt(
        question=question,
        file_names=file_names if file_names else None,
        file_contents=file_contents if file_contents else None
    )
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"Processing task: {task_id}")
        print(f"{'='*80}")
        print(f"Question: {question[:200]}...")
        if file_names:
            print(f"Attachment files: {file_names}")
    
    try:
        # Create CAMEL workflow (with tools)
        graph = create_camel_role_playing_workflow(
            model=model,
            max_conversation_turns=max_conversation_turns,
            word_limit=word_limit,
            tools=GAIA_TOOLS
        )
        graph.build()
        
        # Execute workflow
        result, attributes = graph.invoke({"task": task_prompt})
        
        # Extract answer
        predicted_answer = extract_answer_from_camel_result(result)
        
        # Compare answers
        is_correct = False
        if predicted_answer and correct_answer:
            is_correct = compare_answers(predicted_answer, correct_answer)
        
        if verbose:
            print(f"Predicted answer: {predicted_answer}")
            print(f"Correct answer: {correct_answer}")
            print(f"Is correct: {is_correct}")
        
        return {
            "task_id": task_id,
            "question": question,
            "file_names": file_names,
            "predicted_answer": predicted_answer,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
            "conversation_result": result.get("conversation_result", {})
        }
    
    except Exception as e:
        print(f"\nError: Exception occurred while processing task {task_id}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        
        return {
            "task_id": task_id,
            "question": question,
            "file_names": file_names,
            "predicted_answer": None,
            "correct_answer": correct_answer,
            "is_correct": False,
            "error": str(e)
        }


def evaluate_camel_on_gaia(
    output_file: str,
    model: OpenAIModel,
    data_dir: str = None,
    split: str = "test",
    max_tasks: Optional[int] = None,
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False,
    use_huggingface: bool = True,
) -> Dict:
    """
    Evaluate CAMEL framework on GAIA dataset.
    
    Args:
        output_file: Output JSONL file path.
        model: Model adapter.
        data_dir: Data directory path (None means auto-find).
        split: Dataset split ("test" or "validation").
        max_tasks: Maximum number of tasks to process (None means all).
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
        use_huggingface: Whether to prioritize loading from Hugging Face.
    
    Returns:
        Evaluation result dictionary, containing accuracy and other metrics.
    """
    # Load GAIA tasks
    print(f"Loading GAIA dataset (split={split})...")
    tasks = load_gaia_examples(
        data_dir=data_dir,
        split=split,
        use_huggingface=use_huggingface,
        max_examples=max_tasks
    )
    print(f"Found {len(tasks)} tasks in total")
    
    # Generate answers
    print(f"\nStarting to process tasks using CAMEL framework...")
    results = []
    
    for idx, task in enumerate(tqdm.tqdm(tasks, desc="Processing tasks")):
        task_id = task.get("task_id", task.get("Task", f"task_{idx}"))
        if not task_id:
            task_id = f"task_{idx}"
        
        result = run_camel_on_task(
            task=task,
            task_id=task_id,
            model=model,
            max_conversation_turns=max_conversation_turns,
            word_limit=word_limit,
            verbose=verbose,
            data_dir=data_dir
        )
        results.append(result)
        
        # Save intermediate results every 10 tasks
        if (idx + 1) % 10 == 0:
            print(f"\n[Progress Save] Processed {idx + 1}/{len(tasks)} tasks, saving intermediate results...")
            with open(output_file, 'w', encoding='utf-8') as f:
                for r in results:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')
            print(f"[Progress Save] Intermediate results saved to: {output_file}")
    
    # Save final results
    print(f"\nSaving final results to: {output_file}")
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + '\n')
    
    # Calculate metrics
    print(f"\nCalculating evaluation metrics...")
    total = len(results)
    correct = sum(1 for r in results if r.get("is_correct", False))
    no_answer = sum(1 for r in results if r.get("predicted_answer") is None)
    
    accuracy = correct / total if total > 0 else 0.0
    no_answer_rate = no_answer / total if total > 0 else 0.0
    
    print(f"\n{'='*80}")
    print(f"Evaluation Results:")
    print(f"{'='*80}")
    print(f"Total: {total}")
    print(f"Correct: {correct}")
    print(f"Incorrect: {total - correct - no_answer}")
    print(f"No Answer: {no_answer}")
    print(f"Accuracy: {accuracy:.4f} ({accuracy*100:.2f}%)")
    print(f"No Answer Rate: {no_answer_rate:.4f} ({no_answer_rate*100:.2f}%)")
    print(f"{'='*80}")
    
    return {
        "accuracy": accuracy,
        "total": total,
        "correct": correct,
        "incorrect": total - correct - no_answer,
        "no_answer": no_answer,
        "no_answer_rate": no_answer_rate,
        "output_file": output_file
    }


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate CAMEL framework using GAIA dataset"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Output JSONL file path (default: gaia/result/camel_gaia_samples.jsonl)"
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        default=None,
        help="GAIA data directory path (if not set, auto-find)"
    )
    parser.add_argument(
        "--split",
        type=str,
        default="test",
        choices=["test", "validation"],
        help="Dataset split (test or validation)"
    )
    parser.add_argument(
        "--no_huggingface",
        action="store_true",
        help="Don't use Hugging Face, only load from local files"
    )
    parser.add_argument(
        "--max_tasks",
        type=int,
        default=10,
        help="Maximum number of tasks to process (0 means all, positive means first N)"
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
        "--api_key",
        type=str,
        default=None,
        help="OpenAI API key (must be obtained from OPENAI_API_KEY environment variable)"
    )
    parser.add_argument(
        "--base_url",
        type=str,
        default="https://api.apiyi.com/v1",
        help="OpenAI API base URL (default: https://api.apiyi.com/v1, can also be set via OPENAI_BASE_URL environment variable)"
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default=None,
        help="Model name (if not set, read from OPENAI_MODEL_NAME environment variable, default: gpt-4o-mini)"
    )
    
    args = parser.parse_args()
    
    # Set default output path
    if args.output_file is None:
        gaia_dir = Path(__file__).parent
        result_dir = gaia_dir / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        args.output_file = str(result_dir / f"camel_gaia_{args.split}_samples.jsonl")
    
    # Set model
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    base_url = args.base_url or os.getenv("OPENAI_BASE_URL", "https://api.apiyi.com/v1")
    model_name = args.model_name or os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
    
    if not api_key:
        print("Error: Please set OPENAI_API_KEY environment variable or use --api_key parameter")
        sys.exit(1)
    
    model = OpenAIModel(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name
    )
    
    # Handle max_tasks: 0 or negative means all
    max_tasks = None if args.max_tasks <= 0 else args.max_tasks
    
    # Run evaluation
    evaluate_camel_on_gaia(
        output_file=args.output_file,
        model=model,
        data_dir=args.data_dir,
        split=args.split,
        max_tasks=max_tasks,
        max_conversation_turns=args.max_conversation_turns,
        word_limit=args.word_limit,
        verbose=args.verbose,
        use_huggingface=not args.no_huggingface,
    )


if __name__ == "__main__":
    main()

