"""Evaluate CAMEL framework using GPQA dataset.

This module provides functionality to evaluate the CAMEL role-playing framework
on the GPQA (Graduate-Level Google-Proof Q&A) benchmark.
"""

import os
import sys
import json
import argparse
import random
import pandas as pd
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import namedtuple
import tqdm

# Add parent directory to path for importing CAMEL framework
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import CAMEL framework (must be before importing local modules, as workflow needs to import from camel/prompts)
from workflow import create_camel_role_playing_workflow  # type: ignore
from masfactory import OpenAIModel  # type: ignore

# Use importlib to directly import local modules, avoiding path conflicts
gpqa_dir = Path(__file__).parent

# Import prompts module
prompts_spec = importlib.util.spec_from_file_location(
    "gpqa_prompts",
    gpqa_dir / "prompts.py"
)
gpqa_prompts = importlib.util.module_from_spec(prompts_spec)
prompts_spec.loader.exec_module(gpqa_prompts)
create_task_prompt = gpqa_prompts.create_task_prompt

# Import answer_extractor module
answer_extractor_spec = importlib.util.spec_from_file_location(
    "gpqa_answer_extractor",
    gpqa_dir / "answer_extractor.py"
)
gpqa_answer_extractor = importlib.util.module_from_spec(answer_extractor_spec)
answer_extractor_spec.loader.exec_module(gpqa_answer_extractor)
extract_answer_from_camel_result = gpqa_answer_extractor.extract_answer_from_camel_result

# Define Example named tuple (consistent with GPQA official code)
Example = namedtuple('Example', ['question', 'choice1', 'choice2', 'choice3', 'choice4', 'correct_index'])

# Letter to index mapping
LETTER_TO_INDEX = {'A': 0, 'B': 1, 'C': 2, 'D': 3}


def load_gpqa_examples(data_filename: str = None, seed: int = 0, max_examples: Optional[int] = None, use_huggingface: bool = True) -> List[Example]:
    """
    Load GPQA problems from CSV file or Hugging Face.
    
    Args:
        data_filename: CSV file path (if None and use_huggingface=True, load from Hugging Face).
        seed: Random seed (for shuffling option order).
        max_examples: Maximum number of problems to load (None means all).
        use_huggingface: Whether to prioritize loading from Hugging Face.
    
    Returns:
        List of Examples.
    """
    question_df = None
    
    # Prioritize loading from Hugging Face
    if use_huggingface:
        try:
            print("Attempting to load GPQA dataset from Hugging Face...")
            from datasets import load_dataset
            from huggingface_hub import login
            
            # Try to use Hugging Face token (from environment variable or cache)
            hf_token = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")
            if hf_token:
                try:
                    login(token=hf_token)
                    print("Logged in using Hugging Face token")
                except Exception as login_error:
                    print(f"Warning: Hugging Face login failed: {login_error}")
                    print("Will try to load directly (if already logged in)...")
            
            try:
                dataset = load_dataset("idavidrein/gpqa", "main", token=hf_token)
            except Exception as load_error:
                if "gated" in str(load_error).lower() or "authenticated" in str(load_error).lower():
                    print("Hint: GPQA dataset is a gated dataset, requires Hugging Face authentication.")
                    print("Please follow these steps:")
                    print("1. Visit https://huggingface.co/datasets/idavidrein/gpqa to request access")
                    print("2. Get Hugging Face token: https://huggingface.co/settings/tokens")
                    print("3. Set environment variable: set HUGGINGFACE_TOKEN=your_token_here")
                    print("   Or run: huggingface-cli login")
                    print("Will try to load from local files...")
                else:
                    raise load_error
            
            # Convert to DataFrame
            if "train" in dataset:
                question_df = dataset["train"].to_pandas()
            elif "main" in dataset:
                question_df = dataset["main"].to_pandas()
            else:
                # Take first split
                split_name = list(dataset.keys())[0]
                question_df = dataset[split_name].to_pandas()
            
            print(f"Successfully loaded {len(question_df)} records from Hugging Face")
        except ImportError as import_error:
            print("Warning: datasets library not installed, cannot load from Hugging Face.")
            print("Please run: pip install datasets huggingface_hub")
            print("Will try to load from local files...")
        except Exception as e:
            print(f"Failed to load from Hugging Face: {e}")
            print("Will try to load from local files...")
    
    # If Hugging Face loading failed, try loading from local files
    if question_df is None:
        if data_filename is None:
            data_filename = "dataset/gpqa_main.csv"
        
        # Try multiple possible paths
        possible_paths = [
            Path(data_filename),
            Path(__file__).parent.parent.parent.parent.parent / "datasets" / "gpqa-main" / "gpqa-main" / data_filename,
            Path(__file__).parent.parent.parent.parent.parent / "datasets" / "gpqa-main" / "gpqa-main" / "dataset" / data_filename,
            # Try to find gpqa_main.csv directly (without dataset/ prefix)
            Path(__file__).parent.parent.parent.parent.parent / "datasets" / "gpqa-main" / "gpqa-main" / "gpqa_main.csv",
        ]
        
        data_path = None
        for path in possible_paths:
            if path.exists():
                data_path = path
                break
        
        # If not found, try to check zip file
        if data_path is None:
            zip_path = Path(__file__).parent.parent.parent.parent.parent / "datasets" / "gpqa-main" / "gpqa-main" / "dataset.zip"
            if zip_path.exists():
                print(f"Found dataset.zip file: {zip_path}")
                print("Hint: Data file is in zip archive, needs to be extracted.")
                print(f"Extraction password: deserted-untie-orchid")
                print("Please manually extract dataset.zip to dataset/ directory")
                error_msg = f"Data file is in zip archive, needs to be extracted.\n"
                error_msg += f"Zip file path: {zip_path}\n"
                error_msg += f"Extraction password: deserted-untie-orchid\n"
                error_msg += f"After extraction should contain: dataset/gpqa_main.csv\n"
            else:
                error_msg = f"Cannot find GPQA data file: {data_filename}\n"
                error_msg += f"Tried paths: {[str(p) for p in possible_paths]}\n"
                error_msg += f"Zip file path: {zip_path} (does not exist)\n"
            
            error_msg += "\nSolutions:\n"
            error_msg += "1. Load from Hugging Face (recommended):\n"
            error_msg += "   - Visit https://huggingface.co/datasets/idavidrein/gpqa to request access\n"
            error_msg += "   - Get token: https://huggingface.co/settings/tokens\n"
            error_msg += "   - Set environment variable: set HUGGINGFACE_TOKEN=your_token_here\n"
            error_msg += "   - Or run: huggingface-cli login\n"
            error_msg += "2. Load from local files:\n"
            error_msg += "   - Extract dataset.zip (password: deserted-untie-orchid)\n"
            error_msg += "   - Or download data file from https://huggingface.co/datasets/idavidrein/gpqa\n"
            raise FileNotFoundError(error_msg)
        
        print(f"Loading GPQA data from local file: {data_path}")
        question_df = pd.read_csv(data_path)
    
    random.seed(seed)
    
    def shuffle_choices_and_create_example(row) -> Example:
        """Shuffle choice order and create Example."""
        list_choices = [
            row['Incorrect Answer 1'],
            row['Incorrect Answer 2'],
            row['Incorrect Answer 3'],
            row['Correct Answer']
        ]
        random.shuffle(list_choices)
        example = Example(
            row['Question'],
            list_choices[0],
            list_choices[1],
            list_choices[2],
            list_choices[3],
            list_choices.index(row['Correct Answer'])
        )
        return example
    
    examples = [shuffle_choices_and_create_example(row) for _, row in question_df.iterrows()]
    
    if max_examples is not None and max_examples > 0:
        examples = examples[:max_examples]
    
    return examples


def run_camel_on_question(
    example: Example,
    question_id: int,
    model: OpenAIModel,
    prompt_type: str = "chain_of_thought",
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False
) -> Dict:
    """
    Run CAMEL framework on a single GPQA question.
    
    Args:
        example: GPQA question Example.
        question_id: Question ID.
        model: Model adapter.
        prompt_type: Prompt type.
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
    
    Returns:
        Dictionary containing question_id, predicted_answer, correct_answer, etc.
    """
    # Generate task prompt
    task_prompt = create_task_prompt(
        question=example.question,
        choice1=example.choice1,
        choice2=example.choice2,
        choice3=example.choice3,
        choice4=example.choice4,
        prompt_type=prompt_type
    )
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"Processing question: {question_id}")
        print(f"{'='*80}")
        print(f"Question: {example.question[:100]}...")
        print(f"Choices: A) {example.choice1[:50]}...")
    
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
        
        # Extract answer (pass choices for value matching)
        predicted_answer = extract_answer_from_camel_result(
            result,
            choice1=example.choice1,
            choice2=example.choice2,
            choice3=example.choice3,
            choice4=example.choice4
        )
        
        # Get correct answer
        correct_letter = ['A', 'B', 'C', 'D'][example.correct_index]
        correct_answer_text = [example.choice1, example.choice2, example.choice3, example.choice4][example.correct_index]
        
        is_correct = (predicted_answer == correct_letter) if predicted_answer else False
        
        if verbose:
            print(f"Predicted answer: {predicted_answer}")
            print(f"Correct answer: {correct_letter}")
            print(f"Is correct: {is_correct}")
        
        return {
            "question_id": question_id,
            "question": example.question,
            "choice1": example.choice1,
            "choice2": example.choice2,
            "choice3": example.choice3,
            "choice4": example.choice4,
            "predicted_answer": predicted_answer,
            "correct_answer": correct_letter,
            "correct_answer_text": correct_answer_text,
            "is_correct": is_correct,
            "conversation_result": result.get("conversation_result", {})
        }
    
    except Exception as e:
        print(f"\nError: Exception occurred while processing question {question_id}: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        
        correct_letter = ['A', 'B', 'C', 'D'][example.correct_index]
        correct_answer_text = [example.choice1, example.choice2, example.choice3, example.choice4][example.correct_index]
        
        return {
            "question_id": question_id,
            "question": example.question,
            "choice1": example.choice1,
            "choice2": example.choice2,
            "choice3": example.choice3,
            "choice4": example.choice4,
            "predicted_answer": None,
            "correct_answer": correct_letter,
            "correct_answer_text": correct_answer_text,
            "is_correct": False,
            "error": str(e)
        }


def evaluate_camel_on_gpqa(
    output_file: str,
    model: OpenAIModel,
    data_filename: str = None,
    prompt_type: str = "chain_of_thought",
    max_examples: Optional[int] = None,
    max_conversation_turns: int = 40,
    word_limit: int = 50,
    verbose: bool = False,
    seed: int = 0,
    use_huggingface: bool = True,
) -> Dict:
    """
    Evaluate CAMEL framework on GPQA dataset.
    
    Args:
        output_file: Output JSONL file path.
        model: Model adapter.
        data_filename: GPQA data file path (None means prioritize loading from Hugging Face).
        prompt_type: Prompt type.
        max_examples: Maximum number of problems to process (None means all).
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
        seed: Random seed.
        use_huggingface: Whether to prioritize loading from Hugging Face.
    
    Returns:
        Evaluation result dictionary, containing accuracy and other metrics.
    """
    # Load GPQA problems
    print(f"Loading GPQA dataset...")
    examples = load_gpqa_examples(data_filename, seed=seed, max_examples=max_examples, use_huggingface=use_huggingface)
    print(f"Found {len(examples)} problems in total")
    
    # Generate answers
    print(f"\nStarting to answer questions using CAMEL framework (prompt_type={prompt_type})...")
    results = []
    
    for idx, example in enumerate(tqdm.tqdm(examples, desc="Processing questions")):
        result = run_camel_on_question(
            example=example,
            question_id=idx,
            model=model,
            prompt_type=prompt_type,
            max_conversation_turns=max_conversation_turns,
            word_limit=word_limit,
            verbose=verbose
        )
        results.append(result)
        
        # Save intermediate results every 10 questions
        if (idx + 1) % 10 == 0:
            print(f"\n[Progress Save] Processed {idx + 1}/{len(examples)} questions, saving intermediate results...")
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
    refusals = sum(1 for r in results if r.get("predicted_answer") is None)
    
    accuracy = correct / total if total > 0 else 0.0
    refusal_rate = refusals / total if total > 0 else 0.0
    
    print(f"\n{'='*80}")
    print(f"Evaluation Results:")
    print(f"{'='*80}")
    print(f"Total: {total}")
    print(f"Correct: {correct}")
    print(f"Incorrect: {total - correct - refusals}")
    print(f"Refusals (unable to extract answer): {refusals}")
    print(f"Accuracy: {accuracy:.4f} ({accuracy*100:.2f}%)")
    print(f"Refusal Rate: {refusal_rate:.4f} ({refusal_rate*100:.2f}%)")
    print(f"{'='*80}")
    
    return {
        "accuracy": accuracy,
        "total": total,
        "correct": correct,
        "incorrect": total - correct - refusals,
        "refusals": refusals,
        "refusal_rate": refusal_rate,
        "prompt_type": prompt_type,
        "output_file": output_file
    }


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate CAMEL framework on GPQA dataset"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Output JSONL file path (default: gpqa/result/camel_gpqa_samples.jsonl)"
    )
    parser.add_argument(
        "--data_filename",
        type=str,
        default=None,
        help="GPQA data file path (if not set, prioritize loading from Hugging Face)"
    )
    parser.add_argument(
        "--no_huggingface",
        action="store_true",
        help="Do not use Hugging Face, only load from local file"
    )
    parser.add_argument(
        "--prompt_type",
        type=str,
        default="chain_of_thought",
        choices=["zero_shot", "chain_of_thought", "5_shot", "zero_shot_chain_of_thought"],
        help="Prompt type"
    )
    parser.add_argument(
        "--max_examples",
        type=int,
        default=0,
        help="Maximum number of problems to process (0 means all, positive means first N)"
    )
    parser.add_argument(
        "--max_conversation_turns",
        type=int,
        default=30,
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
        "--seed",
        type=int,
        default=0,
        help="Random seed (for shuffling option order)"
    )
    parser.add_argument(
        "--api_key",
        type=str,
        default=None,
        help="OpenAI API key (must be obtained from environment variable OPENAI_API_KEY)"
    )
    parser.add_argument(
        "--base_url",
        type=str,
        default="https://api.csun.site/v1/",
        help="OpenAI API base URL (default: https://api.csun.site/v1/, can also be set via environment variable OPENAI_BASE_URL)"
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default=None,
        help="Model name (if not set, read from environment variable OPENAI_MODEL_NAME, default: gpt-4o-mini)"
    )
    
    args = parser.parse_args()
    
    # Set default output path
    if args.output_file is None:
        gpqa_dir = Path(__file__).parent
        result_dir = gpqa_dir / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        args.output_file = str(result_dir / f"camel_gpqa_{args.prompt_type}_samples.jsonl")
    
    # Set model: API key must be obtained from environment variable, base_url uses default value or environment variable
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
    
    # Handle max_examples: 0 or negative means all
    max_examples = None if args.max_examples <= 0 else args.max_examples
    
    # Run evaluation
    evaluate_camel_on_gpqa(
        output_file=args.output_file,
        model=model,
        data_filename=args.data_filename,
        prompt_type=args.prompt_type,
        max_examples=max_examples,
        max_conversation_turns=args.max_conversation_turns,
        word_limit=args.word_limit,
        verbose=args.verbose,
        seed=args.seed,
        use_huggingface=not args.no_huggingface,
    )


if __name__ == "__main__":
    main()

