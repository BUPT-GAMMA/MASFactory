"""
Browser Game Agent Composed Graphs

Reusable MASFactory graph structures for the browser game agent, extracted from the
per-mode pipeline functions so the generate / modify / ask flows share topology and read
like the rest of MASFactory (composable, individually testable, visualizer-friendly).

Graphs:
  BrowserGameVerifierGraph  - test-fix retry loop (generator=Fix, verifier=UI+Functional,
                              evidence=CustomNode, routing=pass/fail); see class docstring.
  BrowserGameBuildGraph     - shared generate/modify body:
                              Planning -> Coding -> VerifierGraph -> Doc
  BrowserGameAskGraph       - ask body: ContextLoad -> Analysis

The run_* orchestrators in pipeline.py own setup (environments, runtime, model, visualizer)
and teardown (disk writes + result dict); these graphs own only the in-graph topology.
"""

import os
import json

from masfactory import CustomNode, Loop, LogicSwitch, Graph, Node
from masfactory.utils.hook import masf_hook
from masfactory.components.human.human_chat_visual import HumanChatVisual

from applications.browser_game_agent.components.phases import (
    PlanningPhase,
    IncrementalPlanningPhase,
    CodingPhase,
    UITestPhase,
    FunctionalTestPhase,
    FixPhase,
    DocPhase,
    AnalysisPhase,
)
from applications.browser_game_agent.components.tools import (
    get_game_code,
    validate_html_structure_tool,
    validate_js_logic_tool,
    run_browser_smoke_test_tool,
)
from applications.browser_game_agent.components.retrieval import retrieve_session_context
from applications.browser_game_agent.components.schemas import coerce_bool

MAX_TEST_ROUNDS = 3


# --------------------------------------------------------------------------------------
# Shared low-level helpers (imported by pipeline.py so both share one implementation)
# --------------------------------------------------------------------------------------
def make_memory(_label: str = ""):
    """Return no ad-hoc semantic memory by default.

    InstructorAssistantGraph already appends short chat history memory internally.
    The old SimpleEmbedder/VectorMemory pair was character-hash based and added
    little useful retrieval signal, so session artifact retrieval is now handled
    explicitly where it matters.
    """
    return None


def human_review_enabled() -> bool:
    return os.getenv("BGA_ENABLE_HUMAN_REVIEW", "").strip().lower() in {"1", "true", "yes", "on"}


def refresh_game_code(rt, attributes):
    """Re-read game files from disk into runtime and attributes."""
    rt.game_code = ""
    fresh = get_game_code()
    if fresh:
        attributes["game_code"] = fresh
    return fresh


def safe_json_loads(text: str):
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def count_test_result_rounds(game_dir: str) -> int:
    results_path = os.path.join(str(game_dir), "test_results.json")
    if not os.path.exists(results_path):
        return 0
    try:
        with open(results_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            return len(data.get("rounds") or [])
        return 0
    except Exception:
        return 0


def build_test_summary(attributes: dict) -> str:
    """Build a human-readable test summary string from attributes."""
    game_dir = attributes.get("game_dir")
    if game_dir:
        results_path = os.path.join(str(game_dir), "test_results.json")
        if os.path.exists(results_path):
            try:
                with open(results_path, "r", encoding="utf-8") as f:
                    results = json.load(f)
                if isinstance(results, dict):
                    rounds = list(results.get("rounds") or [])
                elif isinstance(results, list):
                    rounds = results
                else:
                    rounds = []
                lines = []
                for item in rounds:
                    lines.append(
                        f"Round {item.get('round')}: "
                        f"UI={'PASS' if item.get('ui_passed') else 'FAIL'}, "
                        f"Functional={'PASS' if item.get('func_passed') else 'FAIL'}"
                    )
                if lines:
                    return "; ".join(lines)
            except Exception:
                pass
    lines = []
    for n in range(1, MAX_TEST_ROUNDS + 1):
        skipped = attributes.get(f"_round_{n}_skipped")
        if skipped is None:
            break  # round never ran
        if skipped:
            lines.append(f"Round {n}: SKIPPED (early exit)")
        else:
            ui_ok = attributes.get("ui_test_passed")
            func_ok = attributes.get("functional_test_passed")
            lines.append(
                f"Round {n}: UI={'PASS' if ui_ok else 'FAIL'}, "
                f"Functional={'PASS' if func_ok else 'FAIL'}"
            )
    return "; ".join(lines) if lines else "No test results available."


# --------------------------------------------------------------------------------------
# 1. Test-fix loop
# --------------------------------------------------------------------------------------
class BrowserGameVerifierGraph(Loop):
    """Test-fix retry loop for browser games, shaped after the generator-verifier pattern.

    Mapping onto MASFactory's GeneratorVerifierGraph vocabulary (this stays a bespoke Loop
    because the game QA step has two verifiers plus a pre-generator evidence collector, which
    the single-verifier GeneratorVerifierGraph does not natively express):

      - evidence collector : ``round_start`` CustomNode runs the machine tools
                             (validate_html_structure / validate_js_logic / browser smoke test)
                             before any LLM judgement.
      - verifier           : ``ui_test_phase`` (UITestPhase) + ``functional_test_phase``
                             (FunctionalTestPhase), joined into ``test_result_switch``.
      - routing            : both-pass -> terminate; otherwise -> generator.
      - generator          : ``fix_phase`` (FixPhase) rewrites the code, then loops back to the
                             controller for the next round.

    Early exit: the loop terminates as soon as ``_tests_passed`` is set (both verifiers pass).
    """

    def __init__(
        self,
        name,
        config_phase,
        config_role,
        model,
        rt,
        emit,
        max_rounds=MAX_TEST_ROUNDS,
        lesson_store=None,
    ):
        self._config_phase = config_phase
        self._config_role = config_role
        self._model = model
        self._rt = rt
        self._emit = emit
        self._max_rounds = max_rounds
        self._lesson_store = lesson_store
        pull_keys = {
            "task": "The user's game description",
            "game_code": "The current game code",
            "test_checkpoints": "Planning-defined behavior checkpoints",
            "game_dir": "Session output directory",
        }
        push_keys = {
            "game_code": "Latest game code after any fixes",
            "ui_test_passed": "Whether UI test passed",
            "ui_test_report": "UI test report",
            "ui_issues": "UI issues",
            "functional_test_passed": "Whether functional test passed",
            "functional_test_report": "Functional test report",
            "functional_issues": "Functional issues",
            "html_validation": "Static HTML validation evidence",
            "js_validation": "Static JS validation evidence",
            "browser_test_results": "Real browser smoke test evidence",
            "test_evidence": "Combined evidence used by QA",
            "structured_test_result": "Structured TestResultSchema payload",
            "_tests_passed": "Whether both UI and functional tests passed",
            "test_round": "Last executed test round",
        }
        super().__init__(
            name=name,
            max_iterations=max_rounds,
            terminate_condition_function=self._should_stop,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes={"_tests_passed": False},
        )

    def _should_stop(self, _message, attributes):
        return bool(attributes.get("_tests_passed"))

    def _round_num(self, attributes) -> int:
        return max(1, min(int(attributes.get("current_iteration") or 1), self._max_rounds))

    def _collect_machine_evidence(self, round_num: int, attributes: dict) -> dict:
        html_validation = validate_html_structure_tool()
        js_validation = validate_js_logic_tool()
        browser_results = run_browser_smoke_test_tool(round_num=round_num)
        browser = safe_json_loads(browser_results)

        # When Playwright is unavailable the browser tool returns available=False with an
        # install hint. That is NOT a test failure — mark it SKIPPED so the QA LLM does not
        # read a missing runtime as a failing game.
        if self._browser_skipped(browser):
            browser["status"] = "SKIPPED"
            browser["note"] = (
                "Browser smoke test SKIPPED: Playwright/browser unavailable. "
                "Do NOT treat this as a test failure; judge from static evidence only."
            )
            self._emit(
                f"testing_round_{round_num}",
                "warn: browser smoke test SKIPPED (Playwright unavailable); judging from static checks only.",
            )

        evidence = {
            "round": round_num,
            "html_validation": safe_json_loads(html_validation),
            "js_validation": safe_json_loads(js_validation),
            "browser": browser,
        }
        if browser.get("status") == "SKIPPED":
            evidence["browser_status"] = "SKIPPED"
        attributes["html_validation"] = json.dumps(evidence["html_validation"], ensure_ascii=False, indent=2)
        attributes["js_validation"] = json.dumps(evidence["js_validation"], ensure_ascii=False, indent=2)
        attributes["browser_test_results"] = json.dumps(evidence["browser"], ensure_ascii=False, indent=2)
        attributes["test_evidence"] = json.dumps(evidence, ensure_ascii=False, indent=2)
        return evidence

    @staticmethod
    def _browser_skipped(browser: dict) -> bool:
        """True when the browser test did not run because Playwright is unavailable."""
        if not isinstance(browser, dict) or browser.get("available"):
            return False
        details = str(browser.get("details", ""))
        warnings = " ".join(str(w) for w in (browser.get("warnings") or []))
        return "Playwright" in details or "Playwright" in warnings

    def _result_flag(self, key: str, message: dict, attributes: dict) -> bool:
        if key in message:
            return coerce_bool(message.get(key))
        if key in attributes:
            return coerce_bool(attributes.get(key))
        if self._rt.attributes and key in self._rt.attributes:
            return coerce_bool(self._rt.attributes.get(key))
        return False

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        if self._is_built:
            return

        # --- evidence collector ---
        def round_start(message, attributes):
            round_num = self._round_num(attributes)
            attributes["discussion_finished"] = False
            attributes["test_round"] = round_num
            attributes[f"_round_{round_num}_skipped"] = False
            refresh_game_code(self._rt, attributes)
            self._emit(f"testing_round_{round_num}", f"Testing round {round_num}/{self._max_rounds} with static and browser tools...")
            evidence = self._collect_machine_evidence(round_num, attributes)
            self._emit(f"testing_round_{round_num}", "Machine evidence collected; starting LLM UI judgement...")
            return {
                **message,
                "test_round": round_num,
                "game_code": attributes.get("game_code", ""),
                "html_validation": attributes.get("html_validation", ""),
                "js_validation": attributes.get("js_validation", ""),
                "browser_test_results": attributes.get("browser_test_results", ""),
                "test_evidence": attributes.get("test_evidence", ""),
                "machine_evidence": evidence,
            }

        round_start_node = self.create_node(CustomNode, "round_start")
        round_start_node.set_forward(round_start)
        self.edge_from_controller(round_start_node, keys={})

        # --- verifier: UI test ---
        ui_test = self.create_node(
            UITestPhase,
            name="ui_test_phase",
            assistant_role_name="QA Engineer",
            instructor_role_name="Chief Technology Officer",
            assistant_instructions=self._config_role["QA Engineer"],
            instructor_instructions=self._config_role["Chief Technology Officer"],
            phase_instructions=self._config_phase["UITest"]["phase_prompt"],
            tool_instruction=self._config_phase["UITest"].get("tool_instruction", ""),
            model=self._model,
            memory=make_memory("UI_TEST_MEM"),
            max_turns=1,
        )
        self.create_edge(sender=round_start_node, receiver=ui_test, keys={})

        def func_notify(message, attributes):
            round_num = self._round_num(attributes)
            attributes["discussion_finished"] = False
            self._emit(f"testing_round_{round_num}", "[LLM] UI test phase done.")
            self._emit(f"testing_round_{round_num}", f"Functional test round {round_num}/{self._max_rounds}...")
            return message

        func_notify_node = self.create_node(CustomNode, "functional_test_enter")
        func_notify_node.set_forward(func_notify)
        self.create_edge(sender=ui_test, receiver=func_notify_node, keys={})

        # --- verifier: functional test ---
        func_test = self.create_node(
            FunctionalTestPhase,
            name="functional_test_phase",
            assistant_role_name="QA Engineer",
            instructor_role_name="Programmer",
            assistant_instructions=self._config_role["QA Engineer"],
            instructor_instructions=self._config_role["Programmer"],
            phase_instructions=self._config_phase["FunctionalTest"]["phase_prompt"],
            tool_instruction=self._config_phase["FunctionalTest"].get("tool_instruction", ""),
            model=self._model,
            memory=make_memory("FUNC_TEST_MEM"),
            max_turns=1,
        )
        self.create_edge(sender=func_notify_node, receiver=func_test, keys={})

        # --- routing ---
        route = self.create_node(LogicSwitch, "test_result_switch")
        self.create_edge(sender=func_test, receiver=route, keys={})

        def round_passed(message, attributes):
            round_num = self._round_num(attributes)
            attributes["_tests_passed"] = True
            self._emit(f"fixing_round_{round_num}", f"Round {round_num}/{self._max_rounds}: All tests passed; terminating test loop.")
            return message

        passed_node = self.create_node(CustomNode, "tests_passed")
        passed_node.set_forward(round_passed)
        pass_edge = self.create_edge(sender=route, receiver=passed_node, keys={})
        self.edge_to_terminate_node(sender=passed_node, keys={})

        def fix_notify(message, attributes):
            round_num = self._round_num(attributes)
            ui_ok = self._result_flag("ui_test_passed", message, attributes)
            func_ok = self._result_flag("functional_test_passed", message, attributes)
            attributes["_tests_passed"] = ui_ok and func_ok
            attributes["discussion_finished"] = False
            # Cross-session learning: surface fixes that resolved similar past issues.
            if self._lesson_store is not None:
                issues = (attributes.get("ui_issues") or []) + (attributes.get("functional_issues") or [])
                query = " ".join(str(i) for i in issues).strip()
                try:
                    attributes["learned_lessons"] = self._lesson_store.retrieve(query) or ""
                except Exception as exc:
                    self._emit(f"fixing_round_{round_num}", f"warn: lesson retrieval skipped: {exc}")
            self._emit(
                f"testing_round_{round_num}",
                f"[LLM] Functional test phase done. UI={'PASS' if ui_ok else 'FAIL'}, Func={'PASS' if func_ok else 'FAIL'}",
            )
            self._emit(f"fixing_round_{round_num}", f"Round {round_num}/{self._max_rounds}: Issues found; running fix...")
            return message

        fix_notify_node = self.create_node(CustomNode, "fix_enter")
        fix_notify_node.set_forward(fix_notify)
        fail_edge = self.create_edge(sender=route, receiver=fix_notify_node, keys={})

        def both_tests_passed(_message, attrs):
            both = self._result_flag("ui_test_passed", _message, attrs) and self._result_flag(
                "functional_test_passed",
                _message,
                attrs,
            )
            attrs["_tests_passed"] = both
            return both

        def tests_need_fix(message, attrs):
            return not both_tests_passed(message, attrs)

        route.condition_binding(both_tests_passed, pass_edge)
        route.condition_binding(tests_need_fix, fail_edge)

        # --- generator: fix ---
        fix = self.create_node(
            FixPhase,
            name="fix_phase",
            assistant_role_name="Programmer",
            instructor_role_name="Chief Technology Officer",
            assistant_instructions=self._config_role["Programmer"],
            instructor_instructions=self._config_role["Chief Technology Officer"],
            phase_instructions=self._config_phase["Fix"]["phase_prompt"],
            tool_instruction=self._config_phase["Fix"]["tool_instruction"],
            model=self._model,
            memory=make_memory("FIX_MEM"),
            max_turns=1,
        )
        self.create_edge(sender=fix_notify_node, receiver=fix, keys={})

        def fix_done(message, attributes):
            round_num = self._round_num(attributes)
            refresh_game_code(self._rt, attributes)
            self._emit(f"fixing_round_{round_num}", "[LLM] Fix phase done.")
            return {
                **message,
                "game_code": attributes.get("game_code", ""),
                "_tests_passed": bool(attributes.get("_tests_passed")),
            }

        fix_done_node = self.create_node(CustomNode, "fix_done")
        fix_done_node.set_forward(fix_done)
        self.create_edge(sender=fix, receiver=fix_done_node, keys={})
        self.edge_to_controller(sender=fix_done_node, keys={})

        super().build()


# --------------------------------------------------------------------------------------
# 2. Build graph (shared generate + modify body)
# --------------------------------------------------------------------------------------
class BrowserGameBuildGraph(Graph):
    """Shared generate/modify body: Planning -> Coding -> VerifierGraph -> Doc.

    ``mode`` ("generate" | "modify") selects the planning phase class, human-review pull keys,
    emit strings, and whether the coding->test transition runs the generate-only index.html
    extraction fallback. Post-processing (disk writes + result dict) stays in the run_*
    orchestrator, so this graph only owns the in-graph topology.
    """

    def __init__(
        self,
        name,
        mode,
        config_phase,
        config_role,
        model,
        rt,
        emit,
        game_dir,
        max_rounds=MAX_TEST_ROUNDS,
        lesson_store=None,
        pull_keys=None,
        push_keys=None,
        attributes=None,
    ):
        assert mode in ("generate", "modify"), f"Unknown build mode: {mode!r}"
        super().__init__(name, pull_keys, push_keys, attributes)
        self._mode = mode
        self._config_phase = config_phase
        self._config_role = config_role
        self._model = model
        self._rt = rt
        self._emit = emit
        self._game_dir = game_dir
        self._max_rounds = max_rounds
        self._lesson_store = lesson_store

    # --- transitions ---
    def _plan_to_coding(self, message, attributes):
        emit = self._emit
        game_dir = self._game_dir
        if self._mode == "generate":
            emit("planning", "[LLM] Planning phase done.")
        # Fallback: persist design.md if the LLM didn't call save_design_doc_tool
        plan = attributes.get("game_plan", "")
        if plan:
            if isinstance(plan, dict):
                plan = json.dumps(plan, ensure_ascii=False, indent=2)
                attributes["game_plan"] = plan
            design_path = os.path.join(game_dir, "design.md")
            if self._mode == "modify":
                os.makedirs(game_dir, exist_ok=True)
                with open(design_path, "w", encoding="utf-8") as f:
                    f.write(plan)
            elif not os.path.exists(design_path) or os.path.getsize(design_path) == 0:
                os.makedirs(game_dir, exist_ok=True)
                with open(design_path, "w", encoding="utf-8") as f:
                    f.write(plan)
        # Reset so CodingPhase loop starts fresh
        attributes["discussion_finished"] = False
        if not attributes.get("human_design_feedback"):
            attributes["human_design_feedback"] = "AUTO_APPROVED"
        if self._mode == "generate":
            emit("coding", "Design document saved. Starting code generation...")
            emit("coding", "[LLM] Coding phase starting (1 LLM call)...")
        else:
            emit("coding", "Updated design saved. Implementing changes...")
        return message

    def _coding_to_test(self, message, attributes):
        emit = self._emit
        game_dir = self._game_dir
        rt = self._rt
        if self._mode == "generate":
            emit("coding", "[LLM] Coding phase done.")
            # Ensure game files are on disk
            index_path = os.path.join(game_dir, "index.html")
            if not os.path.exists(index_path):
                code = attributes.get("game_code", "")
                if code:
                    import re as _re
                    os.makedirs(game_dir, exist_ok=True)
                    # Try to extract HTML from markdown code blocks
                    html_match = _re.search(
                        r'```(?:html)?\s*(<!DOCTYPE.*?</html>)\s*```',
                        code, _re.DOTALL | _re.IGNORECASE,
                    )
                    if html_match:
                        code = html_match.group(1)
                    elif '<!DOCTYPE' in code.upper() or '<html' in code.lower():
                        # Code might be raw HTML without code fences
                        doc_match = _re.search(
                            r'(<!DOCTYPE[^>]*>.*?</html>)',
                            code, _re.DOTALL | _re.IGNORECASE,
                        )
                        if doc_match:
                            code = doc_match.group(1)
                    with open(index_path, "w", encoding="utf-8") as f:
                        f.write(code)
                    rt.game_code = code
                    attributes["game_code"] = code
                    emit("coding", f"Fallback: extracted game code ({len(code)} chars) to index.html")
                else:
                    emit("coding", "Warning: No game code produced by coding phase")
            else:
                refresh_game_code(rt, attributes)
        else:
            index_path = os.path.join(game_dir, "index.html")
            if os.path.exists(index_path):
                refresh_game_code(rt, attributes)
        # Initialize test loop state; reset discussion_finished for UITestPhase
        attributes["_tests_passed"] = False
        attributes["test_round"] = 0
        attributes["discussion_finished"] = False
        verb = "generated" if self._mode == "generate" else "updated"
        emit("testing_round_1", f"Code {verb}. Starting test round 1/{self._max_rounds}...")
        return message

    def _to_doc(self, message, attributes):
        refresh_game_code(self._rt, attributes)
        attributes["test_results"] = build_test_summary(attributes)
        self._emit("readme", "Tests complete. Writing documentation...")
        if self._mode == "generate":
            self._emit("readme", "[LLM] Doc phase starting (2 LLM calls)...")
        return message

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        config_phase = self._config_phase
        config_role = self._config_role
        model = self._model

        # --- 1. Planning ---
        if self._mode == "generate":
            planning = self.create_node(
                PlanningPhase,
                name="planning_phase",
                assistant_role_name="Game Designer",
                instructor_role_name="Chief Executive Officer",
                assistant_instructions=config_role["Game Designer"],
                instructor_instructions=config_role["Chief Executive Officer"],
                phase_instructions=config_phase["Planning"]["phase_prompt"],
                tool_instruction=config_phase["Planning"]["tool_instruction"],
                model=model,
                memory=make_memory("PLANNING_MEM"),
                max_turns=1,
            )
            human_review_pull = {
                "game_plan": "Generated game design plan",
                "test_checkpoints": "Generated QA checkpoints",
            }
            human_review_push = {
                "human_design_feedback": "Human approval or requested design adjustments. Use AUTO_APPROVED to accept.",
            }
            human_review_name = "human_design_review"
        else:
            planning = self.create_node(
                IncrementalPlanningPhase,
                name="inc_planning_phase",
                assistant_role_name="Game Designer",
                instructor_role_name="Chief Executive Officer",
                assistant_instructions=config_role["Game Designer"],
                instructor_instructions=config_role["Chief Executive Officer"],
                phase_instructions=config_phase["IncrementalPlanning"]["phase_prompt"],
                tool_instruction=config_phase["IncrementalPlanning"]["tool_instruction"],
                model=model,
                memory=make_memory("INC_PLANNING_MEM"),
                max_turns=1,
            )
            human_review_pull = {
                "game_plan": "Updated game design plan",
                "modification_context": "Retrieved context for the modification",
            }
            human_review_push = {
                "human_design_feedback": "Human approval or requested coding constraints. Use AUTO_APPROVED to accept.",
            }
            human_review_name = "human_modification_review"

        self.edge_from_entry(receiver=planning, keys={})

        planning_tail = planning
        if human_review_enabled():
            human_review = self.create_node(
                HumanChatVisual,
                name=human_review_name,
                pull_keys=human_review_pull,
                push_keys=human_review_push,
                connect_timeout_s=0.5,
            )
            self.create_edge(sender=planning, receiver=human_review, keys={})
            planning_tail = human_review

        plan_notify = self.create_node(CustomNode, "plan_notify")
        plan_notify.set_forward(self._plan_to_coding)
        self.create_edge(sender=planning_tail, receiver=plan_notify, keys={})

        # --- 2. Coding ---
        coding = self.create_node(
            CodingPhase,
            name="coding_phase",
            assistant_role_name="Programmer",
            instructor_role_name="Chief Technology Officer",
            assistant_instructions=config_role["Programmer"],
            instructor_instructions=config_role["Chief Technology Officer"],
            phase_instructions=config_phase["Coding"]["phase_prompt"],
            tool_instruction=config_phase["Coding"]["tool_instruction"],
            model=model,
            memory=make_memory("CODING_MEM"),
            max_turns=2,
        )
        self.create_edge(sender=plan_notify, receiver=coding, keys={})

        coding_notify = self.create_node(CustomNode, "coding_notify")
        coding_notify.set_forward(self._coding_to_test)
        self.create_edge(sender=coding, receiver=coding_notify, keys={})

        # --- 3. Test-Fix verifier loop ---
        verifier = self.create_node(
            BrowserGameVerifierGraph,
            name="test_fix_loop",
            config_phase=config_phase,
            config_role=config_role,
            model=model,
            rt=self._rt,
            emit=self._emit,
            max_rounds=self._max_rounds,
            lesson_store=self._lesson_store,
        )
        self.create_edge(sender=coding_notify, receiver=verifier, keys={})

        # --- 4. Doc ---
        doc_notify = self.create_node(CustomNode, "doc_notify")
        doc_notify.set_forward(self._to_doc)
        self.create_edge(sender=verifier, receiver=doc_notify, keys={})

        doc = self.create_node(
            DocPhase,
            name="doc_phase",
            assistant_role_name="Technical Writer",
            instructor_role_name="Chief Product Officer",
            assistant_instructions=config_role["Technical Writer"],
            instructor_instructions=config_role["Chief Product Officer"],
            phase_instructions=config_phase["Doc"]["phase_prompt"],
            tool_instruction=config_phase["Doc"]["tool_instruction"],
            model=model,
            memory=make_memory("DOC_MEM"),
            max_turns=1,
        )
        self.create_edge(sender=doc_notify, receiver=doc, keys={})
        self.edge_to_exit(sender=doc, keys={})

        super().build()


# --------------------------------------------------------------------------------------
# 3. Ask graph
# --------------------------------------------------------------------------------------
class BrowserGameAskGraph(Graph):
    """Ask body: ContextLoad -> Analysis.

    The context-load node retrieves relevant session artifacts via the shared retriever helper
    and stashes them in the ``all_game_files`` attribute for the AnalysisPhase to pull.
    """

    def __init__(
        self,
        name,
        config_phase,
        config_role,
        model,
        rt,
        emit,
        game_dir,
        user_question,
        top_k=6,
        pull_keys=None,
        push_keys=None,
        attributes=None,
    ):
        super().__init__(name, pull_keys, push_keys, attributes)
        self._config_phase = config_phase
        self._config_role = config_role
        self._model = model
        self._rt = rt
        self._emit = emit
        self._game_dir = game_dir
        self._user_question = user_question
        self._top_k = top_k

    def _context_load(self, message, attributes):
        self._emit("asking", "Retrieving relevant game files for analysis...")
        all_files = retrieve_session_context(
            self._user_question, top_k=self._top_k, directory=self._game_dir,
        )
        attributes["all_game_files"] = all_files
        self._emit("asking", "Relevant files loaded. Analyzing your question...")
        return message

    @masf_hook(Node.Hook.BUILD)
    def build(self):
        context_load = self.create_node(CustomNode, "context_load")
        context_load.set_forward(self._context_load)
        self.edge_from_entry(receiver=context_load, keys={})

        analysis = self.create_node(
            AnalysisPhase,
            name="analysis_phase",
            assistant_role_name="Game Analyst",
            instructor_role_name="Chief Executive Officer",
            assistant_instructions=self._config_role["Game Analyst"],
            instructor_instructions=self._config_role["Chief Executive Officer"],
            phase_instructions=self._config_phase["Analysis"]["phase_prompt"],
            tool_instruction=self._config_phase["Analysis"]["tool_instruction"],
            model=self._model,
            memory=make_memory("ANALYSIS_MEM"),
            max_turns=1,
        )
        self.create_edge(sender=context_load, receiver=analysis, keys={})
        self.edge_to_exit(sender=analysis, keys={})

        super().build()


__all__ = [
    "MAX_TEST_ROUNDS",
    "make_memory",
    "human_review_enabled",
    "refresh_game_code",
    "safe_json_loads",
    "count_test_result_rounds",
    "build_test_summary",
    "BrowserGameVerifierGraph",
    "BrowserGameBuildGraph",
    "BrowserGameAskGraph",
]
