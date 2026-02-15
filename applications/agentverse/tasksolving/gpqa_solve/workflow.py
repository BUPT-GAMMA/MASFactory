"""GPQA multiple-choice reasoning workflow graph.

No executor is used; the evaluator only checks output format for early stopping.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from masfactory import OpenAIModel, RootGraph

from applications.agentverse.components.agentverse_vertical_solver_first import (
    AgentverseVerticalSolverFirstDecisionGraph,
)
from applications.agentverse.components.tasksolving.tasksolving_pipeline_graph import (
    TaskSolvingPipelineGraph,
)


def get_agent_config(config: Dict[str, Any], agent_type: str) -> Dict[str, Any] | None:
    for agent in config.get("agents", []):
        if agent.get("agent_type") == agent_type:
            return agent
    return None


def _normalize_agent_config(agent_cfg: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Normalize AgentVerse-style YAML agent config into MASFactory agent kwargs."""
    if agent_cfg is None:
        return None
    cfg = dict(agent_cfg)
    cfg["role_name"] = cfg.get("role_name") or cfg.get("name")
    llm = cfg.get("llm") or {}
    model_settings: Dict[str, Any] = {}
    if llm.get("temperature") is not None:
        model_settings["temperature"] = llm.get("temperature")
    if llm.get("max_tokens") is not None:
        model_settings["max_tokens"] = llm.get("max_tokens")
    if model_settings:
        cfg["model_settings"] = model_settings
    return cfg


def build_gpqa_graph(config: Dict[str, Any]) -> RootGraph:
    root = RootGraph(name="gpqa_solve_task")

    model_config = config.get("model", {})
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")

    invoke_settings = {
        "temperature": model_config.get("temperature", 0.0),
        "max_tokens": model_config.get("max_tokens", 1536),
    }

    model = OpenAIModel(
        model_name=model_config.get("model_name", "gpt-4o-mini"),
        api_key=api_key,
        base_url=base_url,
        invoke_settings=invoke_settings,
    )

    cnt_agents = int(config.get("cnt_agents", 3) or 3)
    if cnt_agents < 2:
        cnt_agents = 2

    solver_config = _normalize_agent_config(get_agent_config(config, "solver"))
    critic_config = _normalize_agent_config(get_agent_config(config, "critic"))

    critic_configs = []
    for i in range(cnt_agents - 1):
        cfg = dict(critic_config) if critic_config else {}
        cfg["role_name"] = cfg.get("role_name") or f"Critic {i+1}"
        critic_configs.append(cfg)

    decision_graph_args = {
        "cls": AgentverseVerticalSolverFirstDecisionGraph,
        "name": "gpqa_vertical_solver_first",
        "solver_config": solver_config or {},
        "critic_configs": critic_configs,
        "model": model,
        "max_inner_turns": 3,
        "shared_memory": True,
        "attributes": {
            "task_description": "",
            "advice": "",
            "previous_plan": "",
            "has_valid_feedback": True,
        },
    }

    role_assigner_config = _normalize_agent_config(get_agent_config(config, "role_assigner")) or {}
    evaluator_config = _normalize_agent_config(get_agent_config(config, "evaluator")) or {}

    pipeline = root.create_node(
        TaskSolvingPipelineGraph,
        name="gpqa_pipeline",
        decision_graph_args=decision_graph_args,
        role_assigner_config=role_assigner_config,
        evaluator_config=evaluator_config,
        executor_config=None,
        executor_type="none",
        model=model,
        max_turn=int(config.get("max_turn", 1) or 1),
        cnt_agents=cnt_agents,
        pull_keys={"task_description": "The question to solve"},
        push_keys={
            "solution": "The final solution from decision graph",
            "score": "Evaluator score (format compliance only)",
            "advice": "Evaluator advice",
            "success": "Whether terminated early",
            "previous_plan": "Latest solution snapshot",
        },
    )

    root.edge_from_entry(receiver=pipeline, keys={"task_description": "The task to solve"})

    root.edge_to_exit(
        sender=pipeline,
        keys={
            "solution": "Final solution",
            "score": "Score",
            "advice": "Advice",
            "success": "Success flag",
        },
    )

    root.build()
    return root
