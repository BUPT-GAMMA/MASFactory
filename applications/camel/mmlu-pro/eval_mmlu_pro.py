"""Evaluate CAMEL framework using MMLU-Pro dataset.

This module provides functionality to evaluate the CAMEL role-playing framework
on the MMLU-Pro multiple-choice question answering benchmark.
"""

import os
import sys
import json
import argparse
import random
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import namedtuple
import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add parent directory to path for importing CAMEL framework
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import CAMEL framework (must be before importing local modules, as workflow needs to import from camel/prompts)
from workflow import create_camel_role_playing_workflow  # type: ignore
from masfactory import OpenAIModel  # type: ignore

# Use importlib to directly import local modules, avoiding path conflicts
mmlu_pro_dir = Path(__file__).parent

# Import prompts module
prompts_spec = importlib.util.spec_from_file_location(
    "mmlu_pro_prompts",
    mmlu_pro_dir / "prompts.py"
)
mmlu_pro_prompts = importlib.util.module_from_spec(prompts_spec)
prompts_spec.loader.exec_module(mmlu_pro_prompts)
create_task_prompt = mmlu_pro_prompts.create_task_prompt

# Import answer_extractor module
answer_extractor_spec = importlib.util.spec_from_file_location(
    "mmlu_pro_answer_extractor",
    mmlu_pro_dir / "answer_extractor.py"
)
mmlu_pro_answer_extractor = importlib.util.module_from_spec(answer_extractor_spec)
answer_extractor_spec.loader.exec_module(mmlu_pro_answer_extractor)
extract_answer_from_camel_result = mmlu_pro_answer_extractor.extract_answer_from_camel_result

# Define Example named tuple (adapted for MMLU-Pro's 10 options)
Example = namedtuple('Example', [
    'question', 'choiceA', 'choiceB', 'choiceC', 'choiceD',
    'choiceE', 'choiceF', 'choiceG', 'choiceH', 'choiceI', 'choiceJ',
    'correct_index'
])

# Letter to index mapping (A-J)
LETTER_TO_INDEX = {chr(ord('A') + i): i for i in range(10)}


def load_mmlu_pro_examples(
    data_dir: str = None,
    split: str = "test",
    max_examples: Optional[int] = None,
    use_huggingface: bool = False,  # Default load from local, as dataset is already downloaded
    seed: int = 0
) -> List[Example]:
    """Load MMLU-Pro questions from JSONL file or Hugging Face.
    
    Args:
        data_dir: Data directory path (if None, try loading from dataset folder)
        split: Dataset split ("test" or "validation").
        max_examples: Maximum number of questions to load (None means all).
        use_huggingface: Whether to prefer loading from Hugging Face.
        seed: Random seed (for shuffling option order).
    
    Returns:
        List of Example objects.
    """
    examples = []
    
    # Default: do not load from Hugging Face, as dataset is already downloaded locally
    # Only load from Hugging Face when --use_huggingface is explicitly specified
    if use_huggingface:
        try:
            # Try loading MMLU-Pro dataset from Hugging Face
            from datasets import load_dataset
            from huggingface_hub import login
            
            # Try using Hugging Face token (from environment variable or cache)
            hf_token = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")
            if hf_token:
                try:
                    login(token=hf_token)
                except Exception as login_error:
                    # Hugging Face login failed, try direct loading if already logged in
                    pass
            
            try:
                # Try multiple possible Hugging Face dataset paths
                dataset_paths = [
                    "TIGER-AI-Lab/MMLU-Pro",
                    "mmlu-pro",
                    "mmlu_pro"
                ]
                
                dataset = None
                for path in dataset_paths:
                    try:
                        dataset = load_dataset(path, token=hf_token)
                        break
                    except Exception as e:
                        continue
                
                if dataset is None:
                    raise Exception("All Hugging Face paths failed")
                
                # Select split
                if split in dataset:
                    split_data = dataset[split]
                elif "test" in dataset:
                    split_data = dataset["test"]
                else:
                    # Take first split
                    split_name = list(dataset.keys())[0]
                    split_data = dataset[split_name]
                
                # Convert to list
                examples_data = [item for item in split_data]
                
            except Exception as load_error:
                if "gated" in str(load_error).lower() or "authenticated" in str(load_error).lower():
                    # MMLU-Pro dataset is gated, requires Hugging Face authentication
                    # Instructions: visit https://huggingface.co/datasets/TIGER-AI-Lab/MMLU-Pro
                    # Set HUGGINGFACE_TOKEN environment variable or run: huggingface-cli login
                    pass
                # Will try loading from local files
                examples_data = []
        except ImportError as import_error:
            # datasets library not installed, cannot load from Hugging Face
            # Install with: pip install datasets huggingface_hub
            # Will try loading from local files
            examples_data = []
        except Exception as e:
            # Failed to load from Hugging Face, will try loading from local files
            examples_data = []
    else:
        examples_data = []
    
    # If Hugging Face loading failed, try loading from local files
    if not examples_data:
        if data_dir is None:
            # Try multiple possible paths
            # __file__ is applications/camel/mmlu-pro/eval_mmlu_pro.py
            # Go up 5 levels to project root
            base_path = Path(__file__).parent.parent.parent.parent.parent
            possible_paths = [
                base_path / "datasets" / "mmlu-pro",  # Dataset folder under project root
                base_path.parent / "datasets" / "mmlu-pro",  # Dataset folder under project parent directory
                base_path / "datasets" / "mmlu-pro-main",
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
                        break
        
        if data_path is None:
            error_msg = f"Cannot find MMLU-Pro data file\n"
            error_msg += f"Tried paths: {[str(p) for p in possible_paths]}\n"
            error_msg += "\nSolutions:\n"
            error_msg += "1. Load from Hugging Face (recommended):\n"
            error_msg += "   - Visit https://huggingface.co/datasets/TIGER-AI-Lab/MMLU-Pro to request access\n"
            error_msg += "   - Get token: https://huggingface.co/settings/tokens\n"
            error_msg += "   - Set environment variable: set HUGGINGFACE_TOKEN=your_token_here\n"
            error_msg += "   - Or run: huggingface-cli login\n"
            error_msg += "2. Load from local files:\n"
            error_msg += "   - Download MMLU-Pro dataset to datasets/mmlu-pro/ directory\n"
            error_msg += "   - Ensure test.jsonl or validation.jsonl file is included\n"
            raise FileNotFoundError(error_msg)
        
        with open(data_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        item = json.loads(line)
                        examples_data.append(item)
                    except json.JSONDecodeError:
                        # Skip invalid JSON lines
                        pass
    
    # Convert to Example objects
    random.seed(seed)
    
    def create_example_from_item(item: Dict) -> Example:
        """Create Example object from data item."""
        question = item.get('question', item.get('Question', ''))
        
        # Get options (MMLU-Pro has 9-10 options A-J)
        # Data format: options is a list, answer is a letter (e.g., "I", "F", "J"), answer_index is an index (0-9)
        options_list = item.get('options', item.get('Options', []))
        
        if isinstance(options_list, list) and len(options_list) > 0:
            # If options is a list, use directly (in order corresponding to A-J)
            # Note: Some questions may have only 9 options, some have 10
            choiceA = options_list[0] if len(options_list) > 0 else ''
            choiceB = options_list[1] if len(options_list) > 1 else ''
            choiceC = options_list[2] if len(options_list) > 2 else ''
            choiceD = options_list[3] if len(options_list) > 3 else ''
            choiceE = options_list[4] if len(options_list) > 4 else ''
            choiceF = options_list[5] if len(options_list) > 5 else ''
            choiceG = options_list[6] if len(options_list) > 6 else ''
            choiceH = options_list[7] if len(options_list) > 7 else ''
            choiceI = options_list[8] if len(options_list) > 8 else ''
            choiceJ = options_list[9] if len(options_list) > 9 else ''
        else:
            # Try other formats (dictionary or other field names)
            choices_dict = item.get('choices', item.get('Choices', {}))
            if isinstance(choices_dict, dict):
                # If choices is a dictionary, use directly
                choiceA = choices_dict.get('A', choices_dict.get('a', ''))
                choiceB = choices_dict.get('B', choices_dict.get('b', ''))
                choiceC = choices_dict.get('C', choices_dict.get('c', ''))
                choiceD = choices_dict.get('D', choices_dict.get('d', ''))
                choiceE = choices_dict.get('E', choices_dict.get('e', ''))
                choiceF = choices_dict.get('F', choices_dict.get('f', ''))
                choiceG = choices_dict.get('G', choices_dict.get('g', ''))
                choiceH = choices_dict.get('H', choices_dict.get('h', ''))
                choiceI = choices_dict.get('I', choices_dict.get('i', ''))
                choiceJ = choices_dict.get('J', choices_dict.get('j', ''))
            else:
                # If choices is a list or other format, try other fields
                choiceA = item.get('choiceA', item.get('A', ''))
                choiceB = item.get('choiceB', item.get('B', ''))
                choiceC = item.get('choiceC', item.get('C', ''))
                choiceD = item.get('choiceD', item.get('D', ''))
                choiceE = item.get('choiceE', item.get('E', ''))
                choiceF = item.get('choiceF', item.get('F', ''))
                choiceG = item.get('choiceG', item.get('G', ''))
                choiceH = item.get('choiceH', item.get('H', ''))
                choiceI = item.get('choiceI', item.get('I', ''))
                choiceJ = item.get('choiceJ', item.get('J', ''))
        
        # Get correct answer
        # Prefer answer_index if it exists, otherwise convert answer letter to index
        answer_index = item.get('answer_index', None)
        if answer_index is not None and isinstance(answer_index, int):
            correct_index = answer_index
        else:
            correct_answer = item.get('answer', item.get('correct_answer', item.get('correct', '')))
            if isinstance(correct_answer, int):
                # If it's a numeric index (0-9), use directly
                correct_index = correct_answer
            elif isinstance(correct_answer, str):
                # If it's a letter (A-J), convert to index
                correct_index = LETTER_TO_INDEX.get(correct_answer.upper(), 0)
            else:
                correct_index = 0
        
        return Example(
            question=question,
            choiceA=choiceA or '',
            choiceB=choiceB or '',
            choiceC=choiceC or '',
            choiceD=choiceD or '',
            choiceE=choiceE or '',
            choiceF=choiceF or '',
            choiceG=choiceG or '',
            choiceH=choiceH or '',
            choiceI=choiceI or '',
            choiceJ=choiceJ or '',
            correct_index=correct_index
        )
    
    examples = [create_example_from_item(item) for item in examples_data]
    
    if max_examples is not None and max_examples > 0:
        examples = examples[:max_examples]
    
    return examples


def run_camel_on_question(
    example: Example,
    question_id: int,
    model: OpenAIModel,
    prompt_type: str = "zero_shot",
    max_conversation_turns: int = 20,
    word_limit: int = 50,
    verbose: bool = False
) -> Dict:
    """Run CAMEL framework on a single MMLU-Pro question.
    
    Args:
        example: MMLU-Pro question Example object.
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
        choiceA=example.choiceA,
        choiceB=example.choiceB,
        choiceC=example.choiceC,
        choiceD=example.choiceD,
        choiceE=example.choiceE,
        choiceF=example.choiceF,
        choiceG=example.choiceG,
        choiceH=example.choiceH,
        choiceI=example.choiceI,
        choiceJ=example.choiceJ,
        prompt_type=prompt_type
    )
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"Processing Question: {question_id}")
        print(f"{'='*80}")
        print(f"Question: {example.question[:100]}...")
        print(f"Option A: {example.choiceA[:50]}...")
    
    try:
        # Create CAMEL workflow
        # For MMLU-Pro Q&A tasks, skip task_specify step as question and options are already in task description
        graph = create_camel_role_playing_workflow(
            model=model,
            max_conversation_turns=max_conversation_turns,
            word_limit=word_limit,
            use_task_specify=False  # Skip task_specify, use original task description directly
        )
        graph.build()
        
        # Execute workflow
        result, attributes = graph.invoke({"task": task_prompt})
        
        # Import conversation monitor (using importlib to avoid path issues)
        conversation_monitor_spec = importlib.util.spec_from_file_location(
            "mmlu_pro_conversation_monitor",
            mmlu_pro_dir / "conversation_monitor.py"
        )
        conversation_monitor = importlib.util.module_from_spec(conversation_monitor_spec)
        conversation_monitor_spec.loader.exec_module(conversation_monitor)
        detect_final_answer = conversation_monitor.detect_final_answer
        truncate_conversation_at_answer = conversation_monitor.truncate_conversation_at_answer
        
        # Check conversation history to see if Final answer has been output
        conversation_result = result.get("conversation_result", {})
        conversation_history = conversation_result.get("conversation_history", [])
        
        # Detect if Final answer format has been output
        final_answer_info = detect_final_answer(conversation_history)
        if final_answer_info:
            answer_idx, extracted_answer = final_answer_info
            if verbose:
                print(f"[Detected] Assistant output Final answer in message {answer_idx+1}: {extracted_answer}")
            
            # If there's a lot of conversation after the answer, truncate conversation history
            if len(conversation_history) > answer_idx + 3:  # Allow at most 2 messages after answer
                truncated_history, _ = truncate_conversation_at_answer(conversation_history)
                # Update conversation history in result
                result["conversation_result"]["conversation_history"] = truncated_history
                result["conversation_result"]["final_user_message"] = "<CAMEL_TASK_DONE>"
                result["conversation_result"]["final_assistant_message"] = conversation_history[answer_idx].get("content", "")
                result["conversation_result"]["task_completed"] = True
                if verbose:
                    print(f"[Optimized] Truncated conversation history: from {len(conversation_history)} to {len(truncated_history)} messages")
            
            # Prefer answer extracted from Final answer format
            predicted_answer = extracted_answer
        else:
            # If Final answer format not detected, use original extraction method
            predicted_answer = extract_answer_from_camel_result(
                result,
                choiceA=example.choiceA,
                choiceB=example.choiceB,
                choiceC=example.choiceC,
                choiceD=example.choiceD,
                choiceE=example.choiceE,
                choiceF=example.choiceF,
                choiceG=example.choiceG,
                choiceH=example.choiceH,
                choiceI=example.choiceI,
                choiceJ=example.choiceJ
            )
        
        # Get correct answer
        correct_letter = chr(ord('A') + example.correct_index)  # A-J
        choices_list = [
            example.choiceA, example.choiceB, example.choiceC, example.choiceD,
            example.choiceE, example.choiceF, example.choiceG, example.choiceH,
            example.choiceI, example.choiceJ
        ]
        correct_answer_text = choices_list[example.correct_index] if example.correct_index < len(choices_list) else ""
        
        is_correct = (predicted_answer == correct_letter) if predicted_answer else False
        
        if verbose:
            print(f"Predicted Answer: {predicted_answer}")
            print(f"Correct Answer: {correct_letter}")
            print(f"Is Correct: {is_correct}")
        
        return {
            "question_id": question_id,
            "question": example.question,
            "choiceA": example.choiceA,
            "choiceB": example.choiceB,
            "choiceC": example.choiceC,
            "choiceD": example.choiceD,
            "choiceE": example.choiceE,
            "choiceF": example.choiceF,
            "choiceG": example.choiceG,
            "choiceH": example.choiceH,
            "choiceI": example.choiceI,
            "choiceJ": example.choiceJ,
            "predicted_answer": predicted_answer,
            "correct_answer": correct_letter,
            "correct_answer_text": correct_answer_text,
            "is_correct": is_correct,
            "conversation_result": result.get("conversation_result", {})
        }
    
    except Exception as e:
        if verbose:
            print(f"\nError: Exception occurred while processing question {question_id}: {e}")
            import traceback
            traceback.print_exc()
        
        correct_letter = chr(ord('A') + example.correct_index)
        choices_list = [
            example.choiceA, example.choiceB, example.choiceC, example.choiceD,
            example.choiceE, example.choiceF, example.choiceG, example.choiceH,
            example.choiceI, example.choiceJ
        ]
        correct_answer_text = choices_list[example.correct_index] if example.correct_index < len(choices_list) else ""
        
        return {
            "question_id": question_id,
            "question": example.question,
            "choiceA": example.choiceA,
            "choiceB": example.choiceB,
            "choiceC": example.choiceC,
            "choiceD": example.choiceD,
            "choiceE": example.choiceE,
            "choiceF": example.choiceF,
            "choiceG": example.choiceG,
            "choiceH": example.choiceH,
            "choiceI": example.choiceI,
            "choiceJ": example.choiceJ,
            "predicted_answer": None,
            "correct_answer": correct_letter,
            "correct_answer_text": correct_answer_text,
            "is_correct": False,
            "error": str(e)
        }


def load_existing_results(output_file: str) -> Dict[int, Dict]:
    """Load existing results file, return mapping from processed question IDs to results.
    
    Args:
        output_file: Result file path.
    
    Returns:
        Dictionary with question_id as key and result dictionary as value.
    """
    existing_results = {}
    output_path = Path(output_file)
    
    if output_path.exists() and output_path.stat().st_size > 0:
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        result = json.loads(line)
                        question_id = result.get('question_id')
                        if question_id is not None:
                            existing_results[question_id] = result
        except Exception as e:
            # Error loading existing results
            existing_results = {}
    
    return existing_results


def evaluate_camel_on_mmlu_pro(
    output_file: str,
    model: OpenAIModel,
    data_dir: str = None,
    split: str = "test",
    prompt_type: str = "chain_of_thought",
    max_examples: Optional[int] = None,
    max_conversation_turns: int = 20,
    word_limit: int = 50,
    verbose: bool = False,
    seed: int = 0,
    use_huggingface: bool = False,  # Default load from local
    n_workers: int = 1,
    resume: bool = True,  # Whether to resume from interruption
    save_interval: int = 100,  # Save every N questions
) -> Dict:
    """Evaluate CAMEL framework on MMLU-Pro dataset.
    
    Args:
        output_file: Output JSONL file path.
        model: Model adapter.
        data_dir: MMLU-Pro data directory path (None means prefer loading from Hugging Face).
        split: Dataset split ("test" or "validation").
        prompt_type: Prompt type.
        max_examples: Maximum number of questions to process (None means all, -1 means only retry refused questions).
        max_conversation_turns: Maximum number of conversation turns.
        word_limit: Word limit for task specification.
        verbose: Whether to print detailed information.
        seed: Random seed.
        use_huggingface: Whether to prefer loading from Hugging Face.
        n_workers: Number of worker threads for parallel processing (1 means serial processing).
    
    Returns:
        Evaluation result dictionary containing accuracy and other metrics.
    """
    # Special handling: max_examples=-1 means only retry refused questions
    retry_refusals = (max_examples == -1)
    
    # Load MMLU-Pro questions
    # If retrying refused questions, load all questions first
    examples = load_mmlu_pro_examples(
        data_dir=data_dir,
        split=split,
        max_examples=None if retry_refusals else max_examples,
        use_huggingface=use_huggingface,
        seed=seed
    )
    
    # Check existing results, support resuming from interruption
    existing_results = {}
    # If retrying refused questions, must load existing results
    if resume or retry_refusals:
        existing_results = load_existing_results(output_file)
        if existing_results:
            if retry_refusals:
                # Find all refused questions (predicted_answer is None or empty string)
                refused_ids = [
                    qid for qid, result in existing_results.items()
                    if result.get('predicted_answer') is None or 
                       (isinstance(result.get('predicted_answer'), str) and result.get('predicted_answer').strip() == '')
                ]
    
    # Filter questions based on mode
    remaining_examples = []
    remaining_indices = []
    
    if retry_refusals:
        # Only process refused questions
        if not existing_results:
            raise FileNotFoundError("Existing results file not found. Cannot retry refused questions. Please run normal evaluation first.")
            return {
                "accuracy": 0.0,
                "total": 0,
                "correct": 0,
                "incorrect": 0,
                "refusals": 0,
                "refusal_rate": 0.0,
                "prompt_type": prompt_type,
                "output_file": output_file
            }
        refused_ids = set([
            qid for qid, result in existing_results.items()
            if result.get('predicted_answer') is None or 
               (isinstance(result.get('predicted_answer'), str) and result.get('predicted_answer').strip() == '')
        ])
        for idx, example in enumerate(examples):
            if idx in refused_ids:
                remaining_examples.append(example)
                remaining_indices.append(idx)
    else:
        # Normal mode: filter out already processed questions
        for idx, example in enumerate(examples):
            if idx not in existing_results:
                remaining_examples.append(example)
                remaining_indices.append(idx)
    
    if not remaining_examples:
        # Load all existing results
        results = [existing_results[i] for i in sorted(existing_results.keys())]
    else:
        # Generate answers
        new_results = []
        results_lock = threading.Lock()  # For thread-safe result list operations
    
    def process_single_question(args):
        """Process a single question function for parallel processing."""
        original_idx, example = args
        try:
            result = run_camel_on_question(
                example=example,
                question_id=original_idx,  # Use original index
                model=model,
                prompt_type=prompt_type,
                max_conversation_turns=max_conversation_turns,
                word_limit=word_limit,
                verbose=verbose
            )
            return original_idx, result
        except Exception as e:
            # Error processing question, return None
            return original_idx, None
    
    def save_results_to_file(results_dict: Dict[int, Dict], output_file: str):
        """Save results to file (thread-safe)."""
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sorted_results = [results_dict[i] for i in sorted(results_dict.keys())]
        # Use temporary file, then atomically replace to avoid file corruption during write
        temp_file = str(output_path) + '.tmp'
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                for r in sorted_results:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')
            # Atomically replace
            if output_path.exists():
                output_path.unlink()
            Path(temp_file).rename(output_path)
        except Exception as e:
            # Error saving intermediate results
            # If temporary file exists, try to delete
            if Path(temp_file).exists():
                try:
                    Path(temp_file).unlink()
                except:
                    pass
    
    if n_workers > 1:
        # Parallel processing
        # Merge existing results and new results
        all_results = existing_results.copy()
        
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            # Submit all tasks (only process remaining questions)
            future_to_idx = {
                executor.submit(process_single_question, (original_idx, example)): original_idx 
                for original_idx, example in zip(remaining_indices, remaining_examples)
            }
            
            # Use tqdm to show progress
            completed = len(existing_results) - len(remaining_examples) if retry_refusals else len(existing_results)
            total_to_process = len(examples)
            with tqdm.tqdm(total=total_to_process, initial=completed, desc="Processing questions") as pbar:
                for future in as_completed(future_to_idx):
                    idx, result = future.result()
                    if result is not None:
                        with results_lock:
                            all_results[idx] = result
                            completed += 1
                            
                            # Save intermediate results every save_interval questions
                            if completed % save_interval == 0 or completed == total_to_process:
                                save_results_to_file(all_results, output_file)
                    pbar.update(1)
        
        # Save one last time to ensure all results are saved
        save_results_to_file(all_results, output_file)
        
        # Merge all results
        results = [all_results[i] for i in sorted(all_results.keys())]
    else:
        # Serial processing (original method)
        # Merge existing results and new results
        all_results = existing_results.copy()
        total_to_process = len(examples)
        completed = len(existing_results) - len(remaining_examples) if retry_refusals else len(existing_results)
        
        # Use tqdm to show progress
        with tqdm.tqdm(total=total_to_process, initial=completed, desc="Processing questions") as pbar:
            for local_idx, (original_idx, example) in enumerate(zip(remaining_indices, remaining_examples)):
                result = run_camel_on_question(
                    example=example,
                    question_id=original_idx,  # Use original index
                    model=model,
                    prompt_type=prompt_type,
                    max_conversation_turns=max_conversation_turns,
                    word_limit=word_limit,
                    verbose=verbose
                )
                all_results[original_idx] = result
                completed += 1
                pbar.update(1)
                
                # Save intermediate results every save_interval questions
                if completed % save_interval == 0 or completed == total_to_process:
                    save_results_to_file(all_results, output_file)
        
        # Save one last time to ensure all results are saved
        save_results_to_file(all_results, output_file)
        
        # Merge all results
        results = [all_results[i] for i in sorted(all_results.keys())]
    
    # Save final results
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + '\n')
    
    # Calculate metrics
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
        description="Evaluate CAMEL framework using MMLU-Pro dataset"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Output JSONL file path (default: mmlu-pro/result/camel_mmlu_pro_samples.jsonl)"
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        default=None,
        help="MMLU-Pro data directory path (if not set, prefer loading from Hugging Face)"
    )
    parser.add_argument(
        "--split",
        type=str,
        default="test",
        choices=["test", "validation", "dev"],
        help="Dataset split (test, validation, or dev)"
    )
    parser.add_argument(
        "--use_huggingface",
        action="store_true",
        help="Load dataset from Hugging Face (default: load from local files)"
    )
    parser.add_argument(
        "--no_resume",
        action="store_true",
        help="Do not resume from existing results, restart evaluation"
    )
    parser.add_argument(
        "--save_interval",
        type=int,
        default=100,
        help="Save intermediate results every N questions (default: 100)"
    )
    parser.add_argument(
        "--prompt_type",
        type=str,
        default="zero_shot",
        choices=["zero_shot", "chain_of_thought", "5_shot", "zero_shot_chain_of_thought"],
        help="Prompt type"
    )
    parser.add_argument(
        "--max_examples",
        type=int,
        default=-1,
        help="Maximum number of questions to process (0 means all, positive number means first N, -1 means only retry refused questions)"
    )
    parser.add_argument(
        "--max_conversation_turns",
        type=int,
        default=10,
        help="Maximum number of conversation turns (default: 20, optimized to reduce runtime)"
    )
    parser.add_argument(
        "--n_workers",
        type=int,
        default=1,
        help="Number of worker threads for parallel processing (default: 1, recommended: 4-8 for faster processing)"
    )
    parser.add_argument(
        "--word_limit",
        type=int,
        default=500,
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
        help="Random seed (for shuffling option order, default: 0)"
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
        mmlu_pro_dir = Path(__file__).parent
        result_dir = mmlu_pro_dir / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        args.output_file = str(result_dir / f"camel_mmlu_pro_{args.prompt_type}_samples.jsonl")
    
    # Set model: API key must be obtained from environment variable, base_url uses default or environment variable
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
    
    # Handle max_examples: 0 means all, -1 means only retry refused questions, positive number means first N
    if args.max_examples == -1:
        max_examples = -1  # Special value, means only retry refused questions
    elif args.max_examples <= 0:
        max_examples = None  # 0 or negative (except -1) means all
    else:
        max_examples = args.max_examples  # Positive number means first N
    
    # Run evaluation
    evaluate_camel_on_mmlu_pro(
        output_file=args.output_file,
        model=model,
        data_dir=args.data_dir,
        split=args.split,
        prompt_type=args.prompt_type,
        max_examples=max_examples,
        max_conversation_turns=args.max_conversation_turns,
        word_limit=args.word_limit,
        verbose=args.verbose,
        seed=args.seed,
        use_huggingface=args.use_huggingface,  # Default False, only load from Hugging Face if explicitly specified
        n_workers=args.n_workers,
        resume=not args.no_resume,  # Default True, unless --no_resume is specified
        save_interval=args.save_interval  # Save every N questions
    )


if __name__ == "__main__":
    main()

