"""HumanEval task workflow graph.

Config-driven builder for a code-generation pipeline.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any

# Ensure repo root is importable when running this file as a script.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from masfactory import RootGraph, OpenAIModel
from applications.agentverse.components.agentverse_vertical_solver_first import AgentverseVerticalSolverFirstDecisionGraph
from applications.agentverse.components.tasksolving.tasksolving_pipeline_graph import TaskSolvingPipelineGraph

def get_agent_config(config: Dict[str, Any],agent_type: str) -> Dict[str, Any]:
    for agent in config.get("agents"):
        if agent["agent_type"] == agent_type:
            return agent
    return None


def _normalize_agent_config(agent_cfg: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Normalize AgentVerse-style YAML agent config into MASFactory agent kwargs."""
    if agent_cfg is None:
        return None
    cfg = dict(agent_cfg)
    # Align naming across task workflows.
    cfg["role_name"] = cfg.get("role_name") or cfg.get("name")
    # Map per-agent LLM settings to MASFactory Agent.model_settings
    llm = cfg.get("llm") or {}
    model_settings: Dict[str, Any] = {}
    if llm.get("temperature") is not None:
        model_settings["temperature"] = llm.get("temperature")
    if llm.get("max_tokens") is not None:
        model_settings["max_tokens"] = llm.get("max_tokens")
    if model_settings:
        cfg["model_settings"] = model_settings
    return cfg

def build_humaneval_graph(config: Dict[str, Any]) -> RootGraph:
    """Build the HumanEval workflow graph from a config dict."""
    
    root = RootGraph(name="humaneval_task")
    model_config = config.get("model", {})
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")

    invoke_settings = {
        "temperature": model_config.get("temperature", 0.0),
        "max_tokens": model_config.get("max_tokens", 2048)
    }

    model = OpenAIModel(
        model_name=model_config.get("model_name", "gpt-4o-mini"),
        api_key=api_key,
        base_url=base_url,
        invoke_settings=invoke_settings
    )
    
    # NOTE: In original AgentVerse tasksolving, `cnt_agents` counts the whole expert group
    # (solver + critics). Critics count is `cnt_agents - 1`.
    cnt_agents = int(config.get("cnt_agents", 2) or 2)
    if cnt_agents < 2:
        cnt_agents = 2
    solver_config = _normalize_agent_config(get_agent_config(config, "solver"))
    critic_config = _normalize_agent_config(get_agent_config(config, "critic"))
    environment_config = config.get("environment", {})
    
    # Build critic configs (critics = cnt_agents - 1).
    critic_configs = []
    for i in range(cnt_agents - 1):
        cfg = dict(critic_config) if critic_config else {}
        # Make each critic distinguishable (helps model role separation).
        cfg["role_name"] = cfg.get("role_name") or f"Critic {i+1}"
        critic_configs.append(cfg)
    
    decision_graph_args = {
        "cls": AgentverseVerticalSolverFirstDecisionGraph,
        "name": "code_generation_decision",
        "solver_config": solver_config,
        "critic_configs": critic_configs,
        "model": model,
        # Match original AgentVerse VerticalSolverFirstDecisionMaker.max_inner_turns (=3).
        "max_inner_turns": 3,
        # Shared HistoryMemory tends to be noisy for HumanEval (large JSON prompts).
        # This task is typically best served by the current draft + critic feedback + evaluator advice.
        "shared_memory": False,
        "attributes": {
            "task_description": "",
            "advice": "",
            "previous_plan": "",
            "has_valid_feedback": True
        }
    }
    role_assigner_config = None
    evaluator_config = None
    executor_config = None
    for agent in config.get("agents"):
        if agent["agent_type"] == "role_assigner":
            role_assigner_config = _normalize_agent_config(agent)
        if agent["agent_type"] == "evaluator":
            evaluator_config = _normalize_agent_config(agent)
        if agent["agent_type"] == "executor":
            executor_config = _normalize_agent_config(agent)
    pipeline = root.create_node(
        TaskSolvingPipelineGraph,
        name="humaneval_pipeline",
        decision_graph_args=decision_graph_args,
        role_assigner_config=role_assigner_config,
        evaluator_config=evaluator_config,
        executor_config=executor_config,
        model=model,
        max_turn=config.get("max_turn", 5),
        cnt_agents=cnt_agents,
        pull_keys={
            "task_description": "The task to solve",
            "workdir": "Per-task working directory for tmp files",
        },
        push_keys={
            "solution": "The final solution from decision graph",
            "score": "The score of the solution",
            "advice": "The advice of the solution",
            "previous_plan": "The previous plan of the solution"
        }
    )

    # Entry → Pipeline
    root.edge_from_entry(
        receiver=pipeline,
        keys={
            "task_description": "The task to solve",
        }
    )
    
    # Pipeline → Exit
    root.edge_to_exit(
        sender=pipeline,
        keys={
            "solution": "Final solution/code",
            "result": "Executor/test output",
            "score": "Evaluation score",
            "advice": "Evaluation advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        }
    )
    root.build()
    return root
