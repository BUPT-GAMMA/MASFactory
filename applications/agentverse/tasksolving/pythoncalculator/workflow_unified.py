"""PythonCalculator workflow builder (config-driven).

Uses `TaskSolvingPipelineGraph` without local code execution (`executor_type="none"`).
"""

import os
import sys
from pathlib import Path
import yaml
from typing import Dict, Any

# Ensure repo root is importable when running this file as a script.
_CUR_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CUR_DIR.parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from masfactory import RootGraph, OpenAIModel
from applications.agentverse.components.agentverse_vertical_solver_first import AgentverseVerticalSolverFirstDecisionGraph
from applications.agentverse.components.tasksolving.tasksolving_pipeline_graph import TaskSolvingPipelineGraph


def get_agent_config(config: Dict[str, Any], agent_type: str) -> Dict[str, Any]:
    for agent in config.get("agents", []):
        if agent["agent_type"] == agent_type:
            return agent
    return None


def load_config(config_path: str = None) -> Dict[str, Any]:
    if config_path is None:
        config_path = str(_CUR_DIR / "../../assets/configs/python_calculator.yaml")
    
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_pythoncalculator_graph(config: Dict[str, Any]) -> RootGraph:
    """Build the PythonCalculator workflow graph from a config dict."""
    
    root = RootGraph(name="pythoncalculator_task")
    
    # Model config.
    model_config = config.get("model", {})
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")

    invoke_settings = {
        "temperature": model_config.get("temperature", 0.7),
        "max_tokens": model_config.get("max_tokens", 2048)
    }

    model = OpenAIModel(
        model_name=model_config.get("model_name", "gpt-4o-mini"),
        api_key=api_key,
        base_url=base_url,
        invoke_settings=invoke_settings
    )
    
    cnt_agents = config.get("cnt_agents", 4)
    max_turn = config.get("max_turn", 3)
    max_inner_turns = config.get("max_inner_turns", 2)
    
    solver_config = get_agent_config(config, "solver")
    critic_config = get_agent_config(config, "critic")
    role_assigner_config = get_agent_config(config, "role_assigner")
    evaluator_config = get_agent_config(config, "evaluator")
    executor_config = get_agent_config(config, "executor")
    
    critic_configs = [critic_config for _ in range(cnt_agents)]
    
    decision_graph_args = {
        "cls": AgentverseVerticalSolverFirstDecisionGraph,
        "name": "code_generation_decision",
        "solver_config": solver_config,
        "critic_configs": critic_configs,
        "model": model,
        "max_inner_turns": max_inner_turns,
        "shared_memory": True,
        "attributes": {
            "task_description": "",
            "advice": "",
            "previous_plan": "",
            "has_valid_feedback": True
        }
    }
    
    pipeline = root.create_node(
        TaskSolvingPipelineGraph,
        name="pythoncalculator_pipeline",
        decision_graph_args=decision_graph_args,
        role_assigner_config=role_assigner_config,
        evaluator_config=evaluator_config,
        executor_config=executor_config,  # Unused in "none" mode; kept for API compatibility.
        model=model,
        max_turn=max_turn,
        cnt_agents=cnt_agents,
        executor_type="none",  # No code execution; evaluate the draft directly.
        success_threshold=8,   # Terminate when score >= 8.
        pull_keys={
            "task_description": "The task to solve",
        },
        push_keys={
            "solution": "The final solution",
            "score": "The score of the solution",
            "advice": "The advice of the solution",
        }
    )

    root.edge_from_entry(
        receiver=pipeline,
        keys={
            "task_description": "The task to solve",
        }
    )
    
    root.edge_to_exit(
        sender=pipeline,
        keys={}
    )
    
    root.build()
    return root


def main():
    import argparse
    from datetime import datetime
    import json
    
    parser = argparse.ArgumentParser(description="Run PythonCalculator task")
    parser.add_argument("--config", type=str, default=None, help="Config file path")
    parser.add_argument("--task", type=str, default=None, help="Task description (override config)")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(_REPO_ROOT / "applications" / "agentverse" / "assets" / "output" / "pythoncalculator"),
        help="Output directory",
    )
    args = parser.parse_args()
    
    config = load_config(args.config)
    
    task_description = args.task or config.get("task_description", "write a simple calculator GUI using Python3.")
    
    print("=" * 80)
    print("🐍 PythonCalculator task (unified pipeline)")
    print("=" * 80)
    print(f"Task: {task_description}")
    print()
    
    print("🔨 Building graph...")
    workflow = build_pythoncalculator_graph(config)
    print("✅ Graph built successfully")
    print()
    
    print("🚀 Running task...")
    print("-" * 80)
    output, attributes = workflow.invoke({"task_description": task_description})
    print("-" * 80)
    print()
    
    print("📊 Results:")
    print(f"  - Score: {output.get('score', 'N/A')}")
    print(f"  - Success: {output.get('success', False)}")
    
    if "solution" in output:
        print(f"\n💡 Solution:\n{output['solution'][:500]}...")
    
    if "advice" in output:
        print(f"\n📝 Advice: {output.get('advice', 'N/A')}")
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"result_{timestamp}.json"
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "task_description": task_description,
            "output": output,
            "attributes": attributes,
            "timestamp": timestamp
        }, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Results saved to: {output_file}")
    print("\n✨ Task completed!")


if __name__ == "__main__":
    main()
