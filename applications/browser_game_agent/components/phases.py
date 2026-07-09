"""
Browser Game Agent Phases

All MASFactory phase classes for the browser game generation pipeline.
"""

from masfactory import Graph, Model, Memory, Node
from masfactory.components.composed_graph.instructor_assistant_graph import InstructorAssistantGraph
from masfactory.utils.hook import masf_hook
from typing import Callable, List, Optional

from applications.browser_game_agent.components.tools import (
    save_game_files_tool,
    save_readme_tool,
    validate_html_structure_tool,
    validate_js_logic_tool,
    run_browser_smoke_test_tool,
    set_explanation_tool,
    save_design_doc_tool,
    save_test_results_tool,
    read_relevant_game_files_tool,
)


def concat_instructions(agent_instructions, phase_instructions):
    if isinstance(phase_instructions, list):
        phase_instructions = "\n".join(phase_instructions)
    if isinstance(agent_instructions, list):
        agent_instructions = "\n".join(agent_instructions)
    return phase_instructions + "\n" + agent_instructions


class GamePhase(Graph):
    """Base phase class for browser game agent pipeline."""

    def __init__(
        self,
        name: str,
        assistant_role_name: str,
        instructor_role_name: str,
        assistant_instructions,
        instructor_instructions,
        phase_instructions,
        model: Model,
        memory: Optional[Memory],
        max_turns: int = 1,
        tools: List[Callable] = None,
        tool_instruction: str = None,
        require_tool_call: bool = False,
    ):
        super().__init__(name)
        self._assistant_role_name = assistant_role_name
        self._instructor_role_name = instructor_role_name
        self._assistant_instructions = concat_instructions(assistant_instructions, phase_instructions)
        self._instructor_instructions = concat_instructions(instructor_instructions, phase_instructions)
        self._memory = memory
        self._model = model
        self._max_turns = max_turns
        self._tools = tools or []
        self._tool_instruction = tool_instruction
        self._require_tool_call = require_tool_call
        self._pull_keys = {}
        self._push_keys = {}

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        assert self._pull_keys is not None
        assert self._push_keys is not None

        if self._tool_instruction:
            if isinstance(self._assistant_instructions, str):
                self._assistant_instructions = self._tool_instruction + self._assistant_instructions
            else:
                self._assistant_instructions = self._tool_instruction + "\n".join(self._assistant_instructions)

        phase_memories = [self._memory] if self._memory is not None else []

        # When a phase MUST produce its output via a tool call (e.g. CodingPhase ->
        # save_game_files_tool), force the assistant's first turn to call a tool
        # (tool_choice="required"; the Agent relaxes it to "auto" after the first call).
        # This is only safe on an assistant-only run: the tool-less instructor turn would
        # otherwise receive tool_choice="required" with no tools and error at the API. So we
        # collapse to a single assistant iteration (max_turns=1 -> max_iterations=1) when
        # enforcing. Enforcement is a no-op if the phase declares no tools.
        enforce_tool_call = bool(self._require_tool_call and self._tools)
        iag_max_turns = 1 if enforce_tool_call else (2 * self._max_turns - 1)
        agent_model_settings = {"tool_choice": "required"} if enforce_tool_call else None

        role_playing = self.create_node(
            InstructorAssistantGraph,
            name=f"{self._name}_role_playing",
            instructor_role_name=self._instructor_role_name,
            instructor_instructions=self._instructor_instructions,
            assistant_role_name=self._assistant_role_name,
            assistant_instructions=self._assistant_instructions,
            phase_instructions="",
            instructor_memories=phase_memories,
            assistant_memories=phase_memories,
            model=self._model,
            max_turns=iag_max_turns,
            assistant_tools=self._tools,
            pull_keys=self._pull_keys,
            push_keys=self._push_keys,
            instructor_first=False,
            agent_model_settings=agent_model_settings,
        )
        self.edge_from_entry(receiver=role_playing, keys={})
        self.edge_to_exit(sender=role_playing, keys={})
        super().build()


class PlanningPhase(GamePhase):
    def __init__(self, *args, **kwargs):
        tools = [save_design_doc_tool]
        super().__init__(*args, **kwargs, tools=tools, require_tool_call=True)
        self._pull_keys = {
            "task": "The user's game description",
            "game_plan_schema": "Structured output contract for the planning result",
            "known_pitfalls": "Recurring bug patterns learned from past games — design to avoid these",
        }
        self._push_keys = {
            "game_plan": "Detailed game design plan including mechanics, elements, and structure",
            "test_checkpoints": "JSON array of verifiable behavior checkpoints for QA testing",
        }


class IncrementalPlanningPhase(GamePhase):
    """Planning phase for modify mode — updates design based on existing code and prior design."""
    def __init__(self, *args, **kwargs):
        tools = [save_design_doc_tool]
        super().__init__(*args, **kwargs, tools=tools, require_tool_call=True)
        self._pull_keys = {
            "task": "The original game description",
            "modification_request": "The user's modification or incremental development request",
            "modification_context": "Retrieved session artifacts relevant to the modification request",
            "game_plan_schema": "Structured output contract for the updated planning result",
            "game_plan": "The existing game design plan",
            "game_code": "The existing game source code",
            "known_pitfalls": "Recurring bug patterns learned from past games — design to avoid these",
        }
        self._push_keys = {
            "game_plan": "Updated game design plan merging original design with new requirements",
            "test_checkpoints": "Updated JSON array of verifiable behavior checkpoints",
        }


class CodingPhase(GamePhase):
    def __init__(self, *args, **kwargs):
        tools = [save_game_files_tool]
        super().__init__(*args, **kwargs, tools=tools, require_tool_call=True)
        self._pull_keys = {
            "task": "The user's game description",
            "game_plan": "The game design plan",
            "human_design_feedback": "Optional human review feedback from MASFactory Human review node",
            "known_pitfalls": "Recurring bug patterns learned from past games — implement to avoid these",
        }
        self._push_keys = {
            "game_code": "The generated HTML/JS/CSS game code",
        }


class ReadmePhase(GamePhase):
    def __init__(self, *args, **kwargs):
        tools = [save_readme_tool]
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The user's game description",
            "game_plan": "The game design plan",
        }
        self._push_keys = {
            "readme": "The README.md content",
        }


class UITestPhase(GamePhase):
    def __init__(self, *args, **kwargs):
        tools = [validate_html_structure_tool, run_browser_smoke_test_tool, save_test_results_tool]
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The user's game description",
            "game_code": "The generated game code",
            "test_round": "Current test round number (1, 2, or 3)",
            "html_validation": "Structured static HTML validation result from validate_html_structure_tool",
            "browser_test_results": "Structured real browser smoke test result from run_browser_smoke_test_tool",
            "test_evidence": "Combined machine evidence collected before LLM QA judgement",
            "test_result_schema": "Structured output contract for persisted test results",
        }
        self._push_keys = {
            "ui_test_passed": "Boolean: whether UI test passed",
            "ui_test_report": "Detailed UI test findings",
            "ui_issues": "List of UI issues found",
        }


class FunctionalTestPhase(GamePhase):
    def __init__(self, *args, **kwargs):
        tools = [validate_js_logic_tool, run_browser_smoke_test_tool, save_test_results_tool]
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The user's game description",
            "game_code": "The generated game code",
            "test_checkpoints": "JSON array of planning-defined verifiable behavior checkpoints",
            "test_round": "Current test round number (1, 2, or 3)",
            "ui_test_passed": "Whether the UI test passed this round",
            "ui_issues": "UI issues found this round",
            "js_validation": "Structured static JavaScript validation result from validate_js_logic_tool",
            "browser_test_results": "Structured real browser smoke test result from run_browser_smoke_test_tool",
            "test_evidence": "Combined machine evidence collected before LLM QA judgement",
            "test_result_schema": "Structured output contract for persisted test results",
        }
        self._push_keys = {
            "functional_test_passed": "Boolean: whether functional test passed",
            "functional_test_report": "Detailed functional test findings",
            "functional_issues": "List of functional issues found",
        }


class FixPhase(GamePhase):
    def __init__(self, *args, **kwargs):
        tools = [save_game_files_tool]
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The user's game description",
            "game_code": "The current game code",
            "ui_test_report": "UI test report",
            "ui_issues": "UI issues to fix",
            "functional_test_report": "Functional test report",
            "functional_issues": "Functional issues to fix",
            "browser_test_results": "Structured real browser smoke test result",
            "test_evidence": "Combined machine evidence from static and browser tests",
            "fix_decision_schema": "Structured output contract for the fix decision",
            "test_round": "Current fix round number (1, 2, or 3)",
            "learned_lessons": "Fixes that resolved similar issues in past games — reuse these",
        }
        self._push_keys = {
            "game_code": "The fixed game code",
        }


class ModificationPhase(GamePhase):
    def __init__(self, *args, **kwargs):
        tools = [save_game_files_tool]
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The original game description",
            "modification_request": "The user's modification request",
            "game_code": "The current game code",
        }
        self._push_keys = {
            "game_code": "The modified game code",
        }


class ExplanationPhase(GamePhase):
    def __init__(self, *args, **kwargs):
        # No tools - rely on push_key to capture explanation from LLM text output
        super().__init__(*args, **kwargs)
        self._pull_keys = {
            "task": "The original game description",
            "user_question": "The user's question about the game",
            "game_code": "The current game code",
        }
        self._push_keys = {
            "explanation": "Your complete answer to the user's question (string, required)",
        }


class DocPhase(GamePhase):
    """Writes IMPLEMENTATION.md and README.md after the test-fix loop completes."""
    def __init__(self, *args, **kwargs):
        tools = [save_readme_tool]
        super().__init__(*args, **kwargs, tools=tools, require_tool_call=True)
        self._pull_keys = {
            "task": "The user's game description",
            "game_plan": "The game design plan",
            "game_code": "The final game code",
            "test_results": "Summary of test rounds (pass/fail per round)",
            "doc_result_schema": "Structured output contract for generated documentation",
        }
        self._push_keys = {
            "readme": "The README.md content",
            "implementation_doc": "The IMPLEMENTATION.md content",
        }


class AnalysisPhase(GamePhase):
    """Single standalone agent that reads all output files and answers user questions."""
    def __init__(self, *args, **kwargs):
        tools = [read_relevant_game_files_tool, set_explanation_tool]
        super().__init__(*args, **kwargs, tools=tools)
        self._pull_keys = {
            "task": "The original game description",
            "user_question": "The user's question or analysis request",
            "all_game_files": "Combined content of all output files (design, code, tests, docs)",
        }
        self._push_keys = {
            "explanation": "The analyst's answer grounded in the game files",
        }
