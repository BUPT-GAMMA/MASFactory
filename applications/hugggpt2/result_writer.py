"""Result saving module for HuggingGPT2.

This module provides functionality to save HuggingGPT2 workflow execution results
to formatted text files for review and analysis.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


def save_result(
    user_input: str,
    result: dict[str, object],
    output_dir: Optional[Path] = None,
) -> Path:
    """Save execution results to a text file.
    
    Args:
        user_input: User input task description.
        result: Execution result dictionary containing tasks, task results, and response.
        output_dir: Output directory path. If None, uses default outputs directory.
    
    Returns:
        Path to the saved output file.
    """
    if output_dir is None:
        current_file = Path(__file__)
        output_dir = current_file.parent / "outputs"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"hugginggpt2_result_{timestamp}.txt"
    
    result_data = result.get("result", result)
    response = result_data.get("response", "")
    task_results = result_data.get("task_results", {})
    tasks = result_data.get("tasks", [])
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("HuggingGPT2 Execution Results\n")
        f.write("=" * 80 + "\n")
        f.write(f"User Input: {user_input}\n")
        f.write("=" * 80 + "\n")
        f.write(f"\nExecution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        if tasks:
            f.write("\n" + "=" * 80 + "\n")
            f.write("Parsed Task List:\n")
            f.write("=" * 80 + "\n")
            f.write(json.dumps(tasks, indent=2, ensure_ascii=False) + "\n")
        
        if task_results:
            f.write("\n" + "=" * 80 + "\n")
            f.write("Task Execution Results:\n")
            f.write("=" * 80 + "\n")
            # Sort task IDs: try to convert to numbers, otherwise sort as strings
            def sort_key(item):
                task_id = item[0]
                # If already a number, use directly
                if isinstance(task_id, (int, float)):
                    return (0, int(task_id))
                # Try to convert to number
                try:
                    return (0, int(task_id))
                except (ValueError, TypeError):
                    # Try to extract numeric part (e.g., 'task_1' -> 1, '1' -> 1)
                    try:
                        import re
                        numbers = re.findall(r'\d+', str(task_id))
                        if numbers:
                            return (1, int(numbers[0]))
                        return (2, str(task_id))  # Pure strings sorted last
                    except:
                        return (2, str(task_id))
            
            for task_id, task_result in sorted(task_results.items(), key=sort_key):
                f.write(f"\nTask {task_id}:\n")
                f.write("-" * 80 + "\n")
                task_info = task_result.get("task", {})
                f.write(f"Task Type: {task_info.get('task', 'unknown')}\n")
                f.write(f"Arguments: {json.dumps(task_info.get('args', {}), indent=2, ensure_ascii=False)}\n")
                
                choose_result = task_result.get("choose model result", {})
                if choose_result:
                    f.write(f"Selected Model: {choose_result.get('id', 'unknown')}\n")
                    f.write(f"Selection Reason: {choose_result.get('reason', '')}\n")
                
                inference_result = task_result.get("inference result", {})
                if inference_result:
                    if "error" in inference_result:
                        f.write(f"Error: {inference_result['error']}\n")
                    else:
                        f.write(f"Inference Result: {json.dumps(inference_result, indent=2, ensure_ascii=False)}\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("Final Response:\n")
        f.write("=" * 80 + "\n")
        f.write(response + "\n")
    
    # Output file path is returned, caller can print if needed
    return output_file

