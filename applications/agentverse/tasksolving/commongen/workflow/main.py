"""CommonGen workflow graph (config-driven).

Uses `executor_type="coverage-test"`; scoring is deterministic (no extra LLM call).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

# Add repo root to the path so `applications.*` imports work when executed as a script.
_CUR_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CUR_DIR.parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from masfactory import RootGraph, OpenAIModel, Model
from masfactory.core.message import ParagraphMessageFormatter, TwinsFieldTextFormatter, LenientJsonMessageFormatter

from applications.agentverse.components.agentverse_vertical_solver_first import (
    AgentverseVerticalSolverFirstDecisionGraph,
)
from applications.agentverse.components.tasksolving.tasksolving_pipeline_graph import (
    TaskSolvingPipelineGraph,
)


def get_agent_config(config: Dict[str, Any], agent_type: str) -> Dict[str, Any] | None:
    for agent in config.get("agents", []) or []:
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


def build_commongen_graph(config: Dict[str, Any]) -> RootGraph:
    """Build the CommonGen workflow graph from a config dict."""
    root = RootGraph(name="commongen_task")

    model_cfg = config.get("model", {}) or {}
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")

    invoke_settings = {
        "temperature": model_cfg.get("temperature", 0.0),
        "max_tokens": model_cfg.get("max_tokens", 1024),
    }

    model = OpenAIModel(
        model_name=model_cfg.get("model_name", "gpt-4o-mini"),
        api_key=api_key,
        base_url=base_url,
        invoke_settings=invoke_settings,
    )

    # In AgentVerse tasksolving configs, `cnt_agents` counts the whole expert group (solver + critics).
    cnt_agents = int(config.get("cnt_agents", 2) or 2)
    if cnt_agents < 2:
        cnt_agents = 2

    solver_config = _normalize_agent_config(get_agent_config(config, "solver")) or {}
    critic_template = _normalize_agent_config(get_agent_config(config, "critic")) or {}
    critic_configs: list[dict[str, Any]] = []
    for i in range(cnt_agents - 1):
        cfg = dict(critic_template)
        cfg["role_name"] = cfg.get("role_name") or f"Critic {i+1}"
        critic_configs.append(cfg)

    env = config.get("environment", {}) or {}
    rule = env.get("rule", {}) or {}
    dm = rule.get("decision_maker", {}) or {}
    max_inner_turns = int(dm.get("max_inner_turns", 3) or 3)

    decision_graph_args = {
        "cls": AgentverseVerticalSolverFirstDecisionGraph,
        "name": "commongen_vertical_solver_first",
        "solver_config": solver_config,
        "critic_configs": critic_configs,
        "model": model,
        "max_inner_turns": max_inner_turns,
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

    # Role assigner outputs a plain numbered list; force a plain-text formatter.
    role_assigner_config.setdefault("formatters", [ParagraphMessageFormatter(), TwinsFieldTextFormatter()])

    pipeline = root.create_node(
        TaskSolvingPipelineGraph,
        name="commongen_pipeline",
        decision_graph_args=decision_graph_args,
        role_assigner_config=role_assigner_config,
        evaluator_config=evaluator_config,
        executor_config=None,
        model=model,
        max_turn=int(config.get("max_turn", 3) or 3),
        cnt_agents=cnt_agents,
        executor_type="coverage-test",
        pull_keys={
            "task_description": "CommonGen concepts (list[str] or comma-separated string)",
        },
        push_keys={
            "solution": "Final text solution",
            "result": "Coverage executor output",
            "score": "Deterministic evaluator score",
            "advice": "Deterministic evaluator advice",
            "previous_plan": "Previous solution snapshot",
        },
    )

    root.edge_from_entry(
        receiver=pipeline,
        keys={"task_description": "The task to solve"},
    )

    root.edge_to_exit(
        sender=pipeline,
        keys={
            "solution": "Final solution",
            "result": "Coverage details",
            "score": "Score",
            "advice": "Advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )

    root.build()
    return root


def create_commongen_graph(
    *,
    task: str,
    model: Model,
    max_turn: int = 3,
    num_critics: int = 2,
    max_inner_turns: int = 3,
) -> RootGraph:
    """Build a CommonGen workflow graph without YAML.

    Intended for local smoke tests. Uses the deterministic coverage executor and
    relies on the caller-provided `model` (can be a DummyModel).
    """
    root = RootGraph(name="commongen_task")

    cnt_agents = max(2, int(num_critics) + 1)
    critic_configs: list[dict[str, Any]] = []
    for i in range(cnt_agents - 1):
        critic_configs.append(
            {
                "role_name": f"Critic {i+1}",
                "prepend_prompt_template": (
                    "You are {role_description}. You are in a discussion group aiming to generate a coherent and "
                    "grammatically correct paragraph containing all the given words.\n\n"
                    "WORDS:\n{task_description}\n\n"
                    "Review the latest solution. If it covers ALL words (or clear variations), end with [Agree]. "
                    "Otherwise, provide missing words and suggestions, ending with [Disagree]."
                ),
                "append_prompt_template": "",
            }
        )

    solver_config: dict[str, Any] = {
        "role_name": "Planner",
        "prepend_prompt_template": (
            "You are {role_description}. Generate a coherent and grammatically correct paragraph containing ALL "
            "the given words (or clear variations).\n\nWORDS:\n{task_description}\n"
        ),
        "append_prompt_template": "",
    }

    decision_graph_args = {
        "cls": AgentverseVerticalSolverFirstDecisionGraph,
        "name": "commongen_vertical_solver_first",
        "solver_config": solver_config,
        "critic_configs": critic_configs,
        "model": model,
        "max_inner_turns": int(max_inner_turns),
        "shared_memory": True,
        "attributes": {
            "task_description": "",
            "advice": "",
            "previous_plan": "",
            "has_valid_feedback": True,
        },
    }

    role_assigner_config: dict[str, Any] = {
        "role_name": "Team Leader",
        "prepend_prompt_template": "",
        "append_prompt_template": (
            "You are the leader of a group of experts. Recruit {cnt_critic_agents} experts (solver + critics) to "
            "generate a good paragraph for the given WORDS.\n\n"
            "WORDS:\n{task_description}\n\n"
            "Return a numbered list of role descriptions only."
        ),
        "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
    }

    # Not used for coverage-test (evaluator is deterministic), but keep it for interface consistency.
    evaluator_config: dict[str, Any] = {
        "role_name": "Evaluator",
        "prepend_prompt_template": "",
        "append_prompt_template": (
            "Return a JSON object with keys score (0 or 1) and advice (string)."
        ),
        "formatters": [ParagraphMessageFormatter(), LenientJsonMessageFormatter()],
    }

    pipeline = root.create_node(
        TaskSolvingPipelineGraph,
        name="commongen_pipeline",
        decision_graph_args=decision_graph_args,
        role_assigner_config=role_assigner_config,
        evaluator_config=evaluator_config,
        executor_config=None,
        model=model,
        max_turn=int(max_turn),
        cnt_agents=cnt_agents,
        executor_type="coverage-test",
        pull_keys={"task_description": "CommonGen concepts"},
        push_keys={
            "solution": "Final paragraph",
            "result": "Coverage output",
            "score": "Score",
            "advice": "Advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )

    root.edge_from_entry(receiver=pipeline, keys={"task_description": "CommonGen concepts"})
    root.edge_to_exit(
        sender=pipeline,
        keys={
            "solution": "Final paragraph",
            "result": "Coverage output",
            "score": "Score",
            "advice": "Advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )

    root.build()
    return root
