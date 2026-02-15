"""HuggingGPT2 main entry point.

This module provides the main entry point for running HuggingGPT2 workflows.
HuggingGPT2 is a JARVIS-like system that orchestrates multiple AI models to
complete complex tasks by breaking them down into subtasks and selecting
appropriate models for each subtask.
"""

import os
import argparse
from masfactory import OpenAIModel
from workflow import create_hugginggpt_workflow
from result_writer import save_result


def main():
    """Run HuggingGPT2 workflow.
    
    This function initializes the HuggingGPT2 workflow with OpenAI model configuration,
    executes the task planning and execution pipeline, and saves the results.
    
    Environment Variables:
        OPENAI_API_KEY: Required. OpenAI API key for model access.
        OPENAI_BASE_URL: Optional. Base URL for OpenAI API (default: https://api.csun.site/v1/).
        OPENAI_MODEL_NAME: Optional. Model name to use (default: gpt-4o-mini).
    
    Args:
        user_input: The task description provided by the user.
                   If not provided, defaults to a game generation task.
        --config: Path to the configuration file (default: config.yaml).
    """
    parser = argparse.ArgumentParser(description="HuggingGPT2 - JARVIS Reproduction")
    parser.add_argument(
        "user_input",
        nargs="?",
        default="Generate a game with UI, including images and code",
        help="User task description"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to configuration file"
    )
    
    args = parser.parse_args()
    user_input = args.user_input
    
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.csun.site/v1/")
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
    
    if not api_key:
        print("\nPlease set OPENAI_API_KEY environment variable")
        return
    
    model = OpenAIModel(api_key=api_key, base_url=base_url, model_name=model_name)
    
    graph = create_hugginggpt_workflow(model=model, config_path=args.config)
    graph.build()
    
    result, attributes = graph.invoke({
        "user_input": user_input,
        "context": ""
    })
    
    tasks = attributes.get("tasks", [])
    task_results = attributes.get("task_results", {})
    response = result.get("response", "")
    
    full_result = {
        "result": {
            "response": response,
            "task_results": task_results,
            "tasks": tasks
        }
    }
    
    save_result(user_input=user_input, result=full_result)
    
    print("\n" + "=" * 80)
    print("Final Response:")
    print("=" * 80)
    print(response)


if __name__ == "__main__":
    main()

