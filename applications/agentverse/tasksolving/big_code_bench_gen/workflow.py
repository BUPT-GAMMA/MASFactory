"""BigCodeBench code generation workflow graph.

Builds a TaskSolvingPipelineGraph configured to run dataset-provided tests locally
(`executor_type="bigcodebench-test"`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

_CUR_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CUR_DIR.parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from masfactory import RootGraph, OpenAIModel
from masfactory.core.message import (
    ParagraphMessageFormatter,
    LenientJsonMessageFormatter,
    TwinsFieldTextFormatter,
)
from applications.agentverse.components.agentverse_vertical_solver_first import AgentverseVerticalSolverFirstDecisionGraph
from applications.agentverse.components.tasksolving.tasksolving_pipeline_graph import TaskSolvingPipelineGraph


def get_agent_config(config: Dict[str, Any], agent_type: str) -> Dict[str, Any] | None:
    for agent in config.get("agents", []):
        if agent.get("agent_type") == agent_type:
            return agent
    return None


def _normalize_agent_config(agent_cfg: Dict[str, Any] | None) -> Dict[str, Any] | None:
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


def build_big_code_bench_gen_graph(config: Dict[str, Any]) -> RootGraph:
    root = RootGraph(name="big_code_bench_gen_task")

    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("BASE_URL")

    model_config = config.get("model", {}) or {}
    invoke_settings = {
        "temperature": model_config.get("temperature", 0.0),
        "max_tokens": model_config.get("max_tokens", 2048),
    }

    model = OpenAIModel(
        model_name=model_config.get("model_name", "gpt-4o-mini"),
        api_key=api_key,
        base_url=base_url,
        invoke_settings=invoke_settings,
    )

    cnt_agents = int(config.get("cnt_agents", 4) or 4)
    if cnt_agents < 2:
        cnt_agents = 2

    solver_config = _normalize_agent_config(get_agent_config(config, "solver"))
    critic_template = _normalize_agent_config(get_agent_config(config, "critic"))
    critic_configs: list[dict[str, Any]] = []
    for i in range(cnt_agents - 1):
        cfg = dict(critic_template) if critic_template else {}
        cfg["role_name"] = cfg.get("role_name") or f"Critic {i+1}"
        critic_configs.append(cfg)

    env = config.get("environment", {}) or {}
    rule = env.get("rule", {}) or {}
    dm = rule.get("decision_maker", {}) or {}
    ex = rule.get("executor", {}) or {}
    max_inner_turns = int(dm.get("max_inner_turns", 3) or 3)
    executor_type = str(ex.get("type") or "bigcodebench-test")
    shared_memory = bool(dm.get("shared_memory", True))

    decision_graph_args = {
        "cls": AgentverseVerticalSolverFirstDecisionGraph,
        "name": "big_code_bench_gen_decision",
        "solver_config": solver_config or {},
        "critic_configs": critic_configs,
        "model": model,
        "max_inner_turns": max_inner_turns,
        # Align closer to original AgentVerse: solver/critics see the discussion history.
        "shared_memory": shared_memory,
        "attributes": {
            "task_description": "",
            "advice": "",
            "previous_plan": "",
            "has_valid_feedback": True,
        },
    }

    role_assigner_config = _normalize_agent_config(get_agent_config(config, "role_assigner")) or {}
    evaluator_config = _normalize_agent_config(get_agent_config(config, "evaluator")) or {}
    executor_config = _normalize_agent_config(get_agent_config(config, "executor")) or {}

    # Role assigner outputs a plain numbered list; force a plain-text formatter.
    role_assigner_config.setdefault("formatters", [ParagraphMessageFormatter(), TwinsFieldTextFormatter()])

    # Executor/evaluator prompts request JSON; recover from invalid escapes.
    executor_config.setdefault("formatters", [ParagraphMessageFormatter(), LenientJsonMessageFormatter()])
    evaluator_config.setdefault("formatters", [ParagraphMessageFormatter(), LenientJsonMessageFormatter()])

    pipeline = root.create_node(
        TaskSolvingPipelineGraph,
        name="big_code_bench_gen_pipeline",
        decision_graph_args=decision_graph_args,
        role_assigner_config=role_assigner_config,
        evaluator_config=evaluator_config,
        executor_config=executor_config,
        model=model,
        max_turn=int(config.get("max_turn", 2) or 2),
        cnt_agents=cnt_agents,
        executor_type=executor_type,
        pull_keys={
            "task_description": "BigCodeBench task prompt",
            "workdir": "Per-task working directory for tmp files",
            "test_code": "BigCodeBench unit test code (python)",
            "entry_point": "Required entry point name (e.g., task_func)",
        },
        push_keys={
            "solution": "Final code solution",
            "result": "Executor output",
            "score": "Evaluator score",
            "advice": "Evaluator advice",
            "previous_plan": "Previous solution snapshot",
        },
    )

    root.edge_from_entry(
        receiver=pipeline,
        keys={"task_description": "BigCodeBench task prompt"},
    )
    root.edge_to_exit(
        sender=pipeline,
        keys={
            "solution": "Final solution/code",
            "result": "Executor/test output",
            "score": "Evaluation score",
            "advice": "Evaluation advice",
            "message": "Compatibility alias of advice",
            "success": "Whether accepted",
        },
    )
    root.build()
    return root
