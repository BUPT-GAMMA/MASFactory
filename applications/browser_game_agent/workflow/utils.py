"""
Browser Game Agent Workflow Utilities
"""

import os
import sys
import json
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from applications.browser_game_agent.components.schemas import (
    DocResultSchema,
    FixDecisionSchema,
    GamePlanSchema,
    TestResultSchema,
    schema_as_text,
)


def get_config():
    """Load configuration file paths."""
    root = os.path.dirname(os.path.dirname(__file__))
    config_dir = os.path.join(root, "assets", "config")
    phase_config_path = os.path.join(config_dir, "PhaseConfig.json")
    role_config_path = os.path.join(config_dir, "RoleConfig.json")
    assert os.path.exists(phase_config_path), f"Missing: {phase_config_path}"
    assert os.path.exists(role_config_path), f"Missing: {role_config_path}"
    return phase_config_path, role_config_path


def load_configs():
    """Return (config_phase dict, config_role dict)."""
    phase_config_path, role_config_path = get_config()
    with open(phase_config_path, "r", encoding="utf-8") as f:
        config_phase = json.load(f)
    with open(role_config_path, "r", encoding="utf-8") as f:
        config_role = json.load(f)
    return config_phase, config_role


def make_environments(session_id: str, task: str, games_dir: str, model_name: str = "gpt-4o-mini"):
    """Build the initial attributes dict for the pipeline."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    game_dir = os.path.join(games_dir, f"{timestamp}_{session_id}")
    os.makedirs(game_dir, exist_ok=True)

    config_phase, config_role = load_configs()

    return {
        "config_phase": config_phase,
        "config_role": config_role,
        "session_id": session_id,
        "task": task,
        "model_name": model_name,
        "game_dir": game_dir,
        "game_plan_schema": schema_as_text(GamePlanSchema),
        "test_result_schema": schema_as_text(TestResultSchema),
        "fix_decision_schema": schema_as_text(FixDecisionSchema),
        "doc_result_schema": schema_as_text(DocResultSchema),
        "game_plan": None,
        "test_checkpoints": [],
        "game_code": None,
        "readme": None,
        "human_design_feedback": "AUTO_APPROVED",
        "modification_context": "",
        "ui_test_passed": None,
        "ui_test_report": None,
        "ui_issues": [],
        "functional_test_passed": None,
        "functional_test_report": None,
        "functional_issues": [],
        "html_validation": None,
        "js_validation": None,
        "browser_test_results": None,
        "test_evidence": None,
        "structured_test_result": None,
        "explanation": None,
        "modification_request": None,
        "user_question": None,
        "discussion_finished": False,
    }
