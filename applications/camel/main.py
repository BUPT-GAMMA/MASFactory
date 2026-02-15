"""CAMEL Role-Playing main entry point.

This module provides the main entry point for running CAMEL role-playing workflows.
It creates a multi-agent conversation system where AI User and AI Assistant agents
collaborate to solve tasks through role-playing.
"""

from masfactory import OpenAIModel
import os
import argparse
from workflow import create_camel_role_playing_workflow
from result_writer import save_conversation_result


def main():
    """Run CAMEL role-playing workflow and save results to a text file.
    
    This function initializes the CAMEL workflow with OpenAI model configuration,
    executes the role-playing conversation, and saves the results.
    
    Environment Variables:
        OPENAI_API_KEY: Required. OpenAI API key for model access.
        OPENAI_BASE_URL: Optional. Base URL for OpenAI API (default: https://api.csun.site/v1/).
        OPENAI_MODEL_NAME: Optional. Model name to use (default: gpt-4o-mini).
    
    Args:
        user_task: The task description (fuzzy idea) to be solved through role-playing.
                   If not provided, defaults to "Create an sample adder by using python".
    """
    parser = argparse.ArgumentParser(description="CAMEL Role-Playing Workflow")
    parser.add_argument(
        "user_task",
        nargs="?",
        default="Create an sample adder by using python",
        help="User task description (fuzzy idea)"
    )
    
    args = parser.parse_args()
    user_task = args.user_task
    
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.csun.site/v1/")
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
    
    if not api_key:
        print("\nPlease set OPENAI_API_KEY environment variable")
        return
    
    model = OpenAIModel(api_key=api_key, base_url=base_url, model_name=model_name)
    graph = create_camel_role_playing_workflow(model=model, max_conversation_turns=40)
    graph.build()
    result, attributes = graph.invoke({"task": user_task})
    save_conversation_result(user_task=user_task, result=result)


if __name__ == "__main__":
    main()

