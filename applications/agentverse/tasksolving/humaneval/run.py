"""Entry point for running the HumanEval code-generation workflow."""

import os
import sys
import argparse
import yaml
import json
from pathlib import Path
from datetime import datetime


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError(f"Cannot locate repo root from: {start}")


# Add repo root to sys.path to avoid fragile fixed-depth assumptions.
project_root = _find_repo_root(Path(__file__).resolve())
sys.path.insert(0, str(project_root))

# Asset paths (relative to repo root).
assets_dir = os.path.join(project_root, "applications", "agentverse", "assets")

from masfactory import Agent, Node
from applications.agentverse.tasksolving.humaneval.workflow import build_humaneval_graph


def load_config(config_path: str) -> dict:
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)
 

def save_result(result: dict, output_path: str):
    # If output_path is a directory (or has no .json/.jsonl suffix), write a timestamped file.
    if os.path.isdir(output_path) or (not output_path.endswith('.json') and not output_path.endswith('.jsonl')):
        os.makedirs(output_path, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(output_path, f"result_{timestamp}.json")
    else:
        output_file = output_path
        output_dir = os.path.dirname(output_file)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Result saved to: {output_file}")

def load_tasks(task_file: str) -> list:
    with open(task_file, 'r', encoding='utf-8') as f:
        if task_file.endswith('.jsonl'):
            return [json.loads(line) for line in f]
        elif task_file.endswith('.json'):
            return json.load(f)
        else:
            raise ValueError(f"Unsupported file format: {task_file}. Only .json and .jsonl are supported.")


def run_with_config(config_path: str, task_file: str, task_id: int, output_file: str, model: str, max_turn: int, cnt_agents: int):
    print("=" * 80)
    print("🚀 HumanEval Code Generation Task")
    print("=" * 80)
    
    config = load_config(config_path)
    print(f"\n📋 Loaded config: {config_path}")
    
    workflow = build_humaneval_graph(config)
    from applications.agentverse.utils import on_forward_before_hook, on_forward_after_hook
    from masfactory import Agent, Node
    tasks = load_tasks(task_file)
    task_list = []
    if task_id == -1:
        task_list = tasks
    else:
        task_list = [tasks[task_id]]
    
    for task in task_list:
        task_description = task["prompt"]
        workflow.hook_register(Node.Hook.FORWARD.AFTER, on_forward_after_hook,recursion=True, target_type=Agent)
        # RootGraph.invoke expects task fields in the input payload (messages).
        result, attributes = workflow.invoke({"task_description": task_description}, {})
        workflow.reset()

        print("=" * 80)
        print("Task description:")
        print("=" * 80)
        print(task_description)
        print("=" * 80)
        print("Result:")
        print("=" * 80)
        print(attributes)
        
        # Prefer previous_plan if solution is empty.
        solution = attributes.get("solution")
        if not solution or solution == "no solution yet.":
            solution = attributes.get("previous_plan", "no solution yet.")
        
        result_to_save = {
            "task_id": task.get("task_id", "unknown"),
            "task_description": task_description,
            "solution": solution,
            "attributes": attributes
        }
        save_result(result_to_save, output_file)
    
    return task_list

def main():
    parser = argparse.ArgumentParser(description="HumanEval Code Generation Task")
    
    parser.add_argument("--config", type=str, help="Path to config YAML file, start from assets/config",default="humaneval-gpt4.yaml")
    parser.add_argument("--task_file", type=str, help="Task file, start from assets/data/",default="tasksolving/humaneval/test.jsonl")
    parser.add_argument("--task_id", type=int, help="Task id, -1 for all tasks",default=-1)
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="Model name")
    parser.add_argument("--max-turn", type=int, default=5, help="Maximum turns")
    parser.add_argument("--cnt-agents", type=int, default=2, help="Number of expert agents")
    parser.add_argument("--output_file", type=str, help="Output file, start from assets/output/",default="humaneval")
    
    args = parser.parse_args()
    config_path = os.path.join(assets_dir, "configs", args.config)
    task_file = os.path.join(assets_dir, "data", args.task_file)
    output_file = os.path.join(assets_dir, "output", args.output_file)
    model = args.model
    max_turn = args.max_turn
    cnt_agents = args.cnt_agents
    
    run_with_config(config_path, task_file, args.task_id, output_file, model, max_turn, cnt_agents)
    

if __name__ == "__main__":
    main()
