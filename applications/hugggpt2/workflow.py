"""HuggingGPT2 workflow definition.

This module defines the workflow for HuggingGPT2, which orchestrates multiple AI models
to complete complex tasks by breaking them down into subtasks and selecting appropriate
models for each subtask.
"""

import os
import json
import yaml
from pathlib import Path
from typing import Optional
from masfactory import RootGraph, OpenAIModel
from components.task_parser import TaskParser
from components.task_executor import TaskExecutor
from components.response_generator import ResponseGenerator


def create_hugginggpt_workflow(
    model: Optional[OpenAIModel] = None,
    config_path: str = "config.yaml"
) -> RootGraph:
    """Create HuggingGPT2 workflow.
    
    This function creates a complete workflow graph for HuggingGPT2, including:
    - Task parsing: Breaks down user input into structured tasks
    - Task execution: Executes tasks using appropriate models
    - Response generation: Integrates results into final response
    
    Args:
        model: Model adapter. If None, will be read from environment variables.
        config_path: Path to configuration file.
    
    Returns:
        RootGraph: Configured workflow graph.
    """
    # Load configuration
    config_file = Path(__file__).parent / config_path
    if config_file.exists():
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    else:
        config = {}
    
    # Create RootGraph
    graph = RootGraph(name="hugginggpt2", attributes={})
    
    # Initialize model
    if model is None:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.csun.site/v1/")
        model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set and model parameter not provided")
        model = OpenAIModel(api_key=api_key, base_url=base_url, model_name=model_name)
    
    # Load model list
    models_file = Path(__file__).parent / config.get("models_file", "data/p0_models.jsonl")
    models = []
    models_map = {}
    models_metadata = {}
    
    if models_file.exists():
        with open(models_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    model_data = json.loads(line)
                    models.append(model_data)
                    task = model_data.get("task", "unknown")
                    if task not in models_map:
                        models_map[task] = []
                    models_map[task].append(model_data)
                    models_metadata[model_data["id"]] = model_data
    
    # Get configuration parameters
    inference_mode = config.get("inference_mode", "hybrid")
    local_deployment = config.get("local_deployment", "full")
    local_endpoint = config.get("local_inference_endpoint", {})
    local_host = local_endpoint.get("host", "localhost")
    local_port = local_endpoint.get("port", 8005)
    local_server = f"http://{local_host}:{local_port}"
    
    huggingface_token = config.get("huggingface", {}).get("token") or os.getenv("HUGGINGFACE_ACCESS_TOKEN")
    proxy = config.get("proxy") or None
    
    num_candidate_models = config.get("num_candidate_models", 5)
    max_description_length = config.get("max_description_length", 100)
    
    # Get demos paths
    demos_dir = Path(__file__).parent / config.get("demos_dir", "demos")
    parse_task_demos = demos_dir / "demo_parse_task.json"
    choose_model_demos = demos_dir / "demo_choose_model.json"
    response_results_demos = demos_dir / "demo_response_results.json"
    
    # Create task parser node
    task_parser = graph.create_node(
        TaskParser,
        name="task_parser",
        model=model,
        demos_path=str(parse_task_demos),
        pull_keys={
            "user_input": "User task description",
            "context": "Conversation history context (optional)"
        },
        push_keys={
            "tasks": "Parsed task list",
            "user_input": "User input (passed through)"
        }
    )
    
    # Create task execution node
    task_executor = graph.create_node(
        TaskExecutor,
        name="task_executor",
        model=model,
        models_map=models_map,
        models_metadata=models_metadata,
        inference_mode=inference_mode,
        local_server=local_server if inference_mode != "huggingface" else None,
        huggingface_token=huggingface_token if inference_mode != "local" else None,
        proxy=proxy,
        num_candidate_models=num_candidate_models,
        max_description_length=max_description_length,
        pull_keys={
            "tasks": "Parsed task list",
            "user_input": "User input"
        },
        push_keys={
            "task_results": "Task execution results",
            "tasks": "Task list (passed through)",
            "user_input": "User input (passed through)"
        }
    )
    
    # Create response generation node
    response_generator = graph.create_node(
        ResponseGenerator,
        name="response_generator",
        model=model,
        demos_path=str(response_results_demos),
        pull_keys={
            "user_input": "User input",
            "task_results": "Task execution results"
        },
        push_keys={
            "response": "Final response text"
        }
    )
    
    # Connect nodes
    graph.edge_from_entry(
        receiver=task_parser,
        keys={
            "user_input": "User task description",
            "context": "Conversation history context (optional, default empty)"
        }
    )
    
    graph.create_edge(
        sender=task_parser,
        receiver=task_executor,
        keys={
            "tasks": "Parsed task list",
            "user_input": "User input"
        }
    )
    
    graph.create_edge(
        sender=task_executor,
        receiver=response_generator,
        keys={
            "task_results": "Task execution results",
            "user_input": "User input"
        }
    )
    
    graph.edge_to_exit(
        sender=response_generator,
        keys={"response": "Final response text"}
    )
    
    return graph

