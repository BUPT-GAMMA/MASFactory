"""GAIA evaluation prompt templates."""

from typing import List, Optional


def create_task_prompt(
    question: str,
    file_names: Optional[List[str]] = None,
    file_contents: Optional[dict] = None
) -> str:
    """
    Convert GAIA task to task description understandable by CAMEL framework.
    
    Args:
        question: GAIA task question description.
        file_names: List of attached file names (optional).
        file_contents: Dictionary of attached file contents, key is file name, value is file content (optional).
    
    Returns:
        Task description string.
    """
    task_description = f"""Solve the following task. This is a complex reasoning task that may require:
1. Reading and understanding the question carefully
2. Analyzing any provided files or data
3. Performing calculations or computations if needed
4. Using logical reasoning to arrive at the answer
5. Providing a clear and accurate final answer

TASK:
{question}
"""
    
    # If there are attached files, add to task description
    if file_names:
        task_description += "\n\nATTACHED FILES:\n"
        for file_name in file_names:
            task_description += f"- {file_name}\n"
        
        # If there is file content, directly include in prompt
        if file_contents:
            task_description += "\nFILE CONTENTS:\n"
            for file_name, content in file_contents.items():
                if file_name in file_names:
                    task_description += f"\n--- {file_name} ---\n"
                    # Limit file content length to avoid prompt being too long
                    if isinstance(content, str):
                        if len(content) > 5000:
                            task_description += content[:5000] + "\n... (truncated)"
                        else:
                            task_description += content
                    else:
                        task_description += str(content)
                    task_description += "\n"
    
    task_description += """
IMPORTANT REQUIREMENTS FOR THE ASSISTANT:
- Read and understand the task carefully
- If files are provided, you can use the read_file, read_csv, or read_json tools to read them
- Use the calculate tool for mathematical computations
- Use list_files to explore directories if needed
- Use search_in_file to find specific information in files
- Perform any necessary calculations step by step
- Show your reasoning process clearly
- Provide a clear, concise final answer
- **CRITICAL**: In your FINAL response, you MUST explicitly state your final answer
- The answer should be accurate and complete

AVAILABLE TOOLS:
- read_file(file_path): Read the contents of a text file
- read_csv(file_path, delimiter=","): Read and parse a CSV file
- read_json(file_path): Read and parse a JSON file
- calculate(expression): Evaluate a mathematical expression safely
- list_files(directory="."): List files in a directory
- search_in_file(file_path, search_term): Search for text in a file
- get_file_info(file_path): Get file information (size, line count)

IMPORTANT REQUIREMENTS FOR THE USER:
- After the Assistant has provided their reasoning and analysis, you MUST ask for the final answer:
  "Please provide your final answer clearly and concisely."
- After receiving the answer, immediately send <CAMEL_TASK_DONE>

CRITICAL FINAL ANSWER FORMAT:
The Assistant's final response should clearly state the answer. The answer format depends on the question:
- For numerical answers: provide the number (e.g., "42" or "3.14")
- For text answers: provide the complete answer text
- For multiple choice: provide the letter or option (e.g., "A" or "Option 1")
- Make sure the answer is complete and accurate
"""
    
    return task_description


def create_task_prompt_with_files(
    question: str,
    file_names: List[str],
    file_paths: Optional[List[str]] = None
) -> str:
    """
    Create task prompt with file references (file contents need to be read separately).
    
    Args:
        question: GAIA task question description.
        file_names: List of attached file names.
        file_paths: List of attached file paths (optional).
    
    Returns:
        Task description string.
    """
    task_description = f"""Solve the following task. This task includes attached files that you need to read and analyze.

TASK:
{question}

ATTACHED FILES:
"""
    
    for i, file_name in enumerate(file_names):
        if file_paths and i < len(file_paths):
            task_description += f"- {file_name} (path: {file_paths[i]})\n"
        else:
            task_description += f"- {file_name}\n"
    
    task_description += """
IMPORTANT REQUIREMENTS FOR THE ASSISTANT:
- You MUST read and analyze ALL attached files using the available tools
- Use read_file, read_csv, or read_json tools to read file contents
- Extract relevant information from the files
- Use the calculate tool for any mathematical computations needed
- Use search_in_file to find specific information if needed
- Use the information from files to solve the task
- Perform any necessary calculations or reasoning
- Show your work step by step
- Provide a clear, accurate final answer based on the file contents

AVAILABLE TOOLS:
- read_file(file_path): Read the contents of a text file
- read_csv(file_path, delimiter=","): Read and parse a CSV file
- read_json(file_path): Read and parse a JSON file
- calculate(expression): Evaluate a mathematical expression safely
- list_files(directory="."): List files in a directory
- search_in_file(file_path, search_term): Search for text in a file
- get_file_info(file_path): Get file information (size, line count)

IMPORTANT REQUIREMENTS FOR THE USER:
- After the Assistant has analyzed the files and provided reasoning, ask for the final answer:
  "Please provide your final answer based on your analysis."
- After receiving the answer, immediately send <CAMEL_TASK_DONE>

CRITICAL FINAL ANSWER FORMAT:
The Assistant's final response should clearly state the answer derived from the file analysis.
"""
    
    return task_description

