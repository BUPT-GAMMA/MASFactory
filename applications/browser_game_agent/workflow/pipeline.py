"""
Browser Game Agent Pipeline

Builds and runs the MASFactory RootGraph for browser game generation.
Supports three modes: 'generate', 'modify', 'ask'.

Pipeline structure (graph bodies live in workflow/graphs.py):
  generate: pre → BrowserGameBuildGraph(generate) → post
  modify:   pre → BrowserGameBuildGraph(modify)   → post
  ask:      BrowserGameAskGraph → post

Each run_* orchestrator owns setup (environments, runtime, model, visualizer) and teardown
(disk-write fallbacks + result dict); the composed graphs own the in-graph topology.
"""

import os
import sys
import json
import logging
from typing import Callable, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from masfactory import RootGraph, CustomNode
from masfactory.adapters.model.legacy_openai import LegacyOpenAIModel as OpenAIModel

from applications.browser_game_agent.workflow.utils import load_configs, make_environments
from applications.browser_game_agent.workflow.graphs import (
    MAX_TEST_ROUNDS,
    BrowserGameBuildGraph,
    BrowserGameAskGraph,
    count_test_result_rounds,
    build_test_summary,
)
from applications.browser_game_agent.components.memory_store import LessonStore
from applications.browser_game_agent.components.tools import (
    GameRuntimeContext,
    set_game_runtime,
    get_game_code,
    read_relevant_game_files_tool,
)
from applications.browser_game_agent.components.schemas import (
    DocResultSchema,
    FixDecisionSchema,
    GamePlanSchema,
    TestResultSchema,
    schema_as_text,
)

DEFAULT_MODEL = "gpt-4o-mini"


def _games_dir():
    root = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(root, "assets", "output", "games")


def _lessons_path():
    """Location of the global cross-session lesson store (shared by all games)."""
    root = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(root, "assets", "output", "memory", "lessons.json")


def _safe_write(path, content, emit, label="file"):
    """Write text to disk, surfacing failures via emit instead of swallowing them."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as exc:
        emit("warn", f"Failed to write {label} ({path}): {exc}")
        return False


def _capture_lessons(store, model, environments, game_dir, emit):
    """Distill this session's issues into cross-session lessons (best-effort)."""
    try:
        recorded = store.distill_and_record(
            model,
            {
                "task": environments.get("task", ""),
                "ui_issues": environments.get("ui_issues"),
                "functional_issues": environments.get("functional_issues"),
                "test_results": build_test_summary(environments),
            },
            example=os.path.basename(str(game_dir).rstrip("/")),
        )
        if recorded:
            emit("done", f"Recorded {recorded} cross-session lesson(s) for future games.")
    except Exception as exc:
        emit("warn", f"Lesson capture skipped: {exc}")


def _normalize_base_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url = url + "/v1"
    return url


def _connect_visualizer_trace(session_id: str, emit: Callable[[str, str], None]):
    """Best-effort connection to MASFactory Visualizer when enabled by env vars."""
    try:
        from masfactory.visualizer import connect, is_available
    except Exception:
        return None
    try:
        if not is_available():
            return None
        client = connect(timeout_s=0.2)
        if client is not None:
            client.log("info", f"[browser_game_agent] session={session_id} trace connected")
            emit("init", "MASFactory Visualizer tracing connected.")
        return client
    except Exception as exc:
        logging.debug("Visualizer trace unavailable: %s", exc)
        return None


def _execute_graph(graph, environments: dict, visualizer=None):
    """Build and invoke a RootGraph with optional MASFactory Visualizer runtime hooks."""
    graph.build()
    if visualizer is not None:
        try:
            visualizer.attach_graph(graph)
            visualizer.begin_run(graph, input={})
        except Exception:
            pass
    try:
        graph.invoke(input={}, attributes=environments)
    except Exception as exc:
        if visualizer is not None:
            try:
                visualizer.log("error", f"[run] failed graph={getattr(graph, 'name', 'unknown')} error={exc}")
            except Exception:
                pass
        raise
    finally:
        if visualizer is not None:
            try:
                visualizer.end_run(
                    graph,
                    output={
                        "session_id": environments.get("session_id"),
                        "game_dir": environments.get("game_dir"),
                        "_tests_passed": environments.get("_tests_passed"),
                    },
                )
            except Exception:
                pass


def _schema_contracts() -> dict:
    return {
        "game_plan_schema": schema_as_text(GamePlanSchema),
        "test_result_schema": schema_as_text(TestResultSchema),
        "fix_decision_schema": schema_as_text(FixDecisionSchema),
        "doc_result_schema": schema_as_text(DocResultSchema),
    }


def run_generate_pipeline(
    session_id: str,
    task: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    model_name: str = DEFAULT_MODEL,
) -> dict:
    """
    Run the full game generation pipeline:
    Planning → Coding → [UITest → FuncTest → Fix] × 3 → Doc → post
    """
    games_dir = _games_dir()
    environments = make_environments(session_id, task, games_dir, model_name)
    game_dir = environments["game_dir"]

    def emit(stage: str, msg: str):
        logging.info(f"[{session_id}] [{stage}] {msg}")
        if progress_callback:
            progress_callback(stage, msg)

    # Cross-session learning: surface known pitfalls from past games to Planning/Coding.
    lesson_store = LessonStore(_lessons_path(), api_key=api_key, base_url=base_url)
    environments["known_pitfalls"] = lesson_store.retrieve(task) or ""
    environments.setdefault("learned_lessons", "")

    rt = GameRuntimeContext(
        session_id=session_id,
        directory=game_dir,
        task=task,
        attributes=environments,
        progress_callback=emit,
    )
    set_game_runtime(rt)

    emit("init", f"Starting game generation for session {session_id}")

    try:
        model = OpenAIModel(model_name=model_name, api_key=api_key, base_url=_normalize_base_url(base_url))
        visualizer = _connect_visualizer_trace(session_id, emit)
        environments["visualizer_trace"] = bool(visualizer)

        graph = RootGraph(name=f"browser_game_agent_{session_id}", attributes=environments)

        # --- pre ---
        def pre_proc(message, attributes):
            emit("planning", "Analyzing your game description...")
            emit("planning", "[LLM] Planning phase starting (2 LLM calls)...")
            return message

        pre = graph.create_node(CustomNode, "pre_processing")
        pre.set_forward(pre_proc)
        graph.edge_from_entry(receiver=pre, keys={})

        # --- build body (Planning → Coding → Test-Fix loop → Doc) ---
        build_body = graph.create_node(
            BrowserGameBuildGraph,
            name="build_body",
            mode="generate",
            config_phase=environments["config_phase"],
            config_role=environments["config_role"],
            model=model,
            rt=rt,
            emit=emit,
            game_dir=game_dir,
            max_rounds=MAX_TEST_ROUNDS,
            lesson_store=lesson_store,
        )
        graph.create_edge(sender=pre, receiver=build_body, keys={})

        # --- Post processing ---
        def post_proc(message, attributes):
            emit("readme", "[LLM] Doc phase done.")
            for key in [
                "game_plan", "test_checkpoints", "game_code", "readme",
                "implementation_doc",
                "ui_test_passed", "ui_test_report", "ui_issues",
                "functional_test_passed", "functional_test_report", "functional_issues",
                "html_validation", "js_validation", "browser_test_results",
                "test_evidence", "structured_test_result", "human_design_feedback",
                "_tests_passed",
            ]:
                val = attributes.get(key)
                if val is not None:
                    environments[key] = val
            if not environments.get("game_code"):
                environments["game_code"] = get_game_code()
            # Persist test_checkpoints for modify pipeline
            checkpoints = environments.get("test_checkpoints")
            if checkpoints:
                checkpoints_path = os.path.join(game_dir, ".test_checkpoints.json")
                _safe_write(checkpoints_path, json.dumps(checkpoints, ensure_ascii=False), emit, "test_checkpoints")
            # Write IMPLEMENTATION.md if doc phase produced it
            impl_doc = environments.get("implementation_doc")
            if impl_doc:
                impl_path = os.path.join(game_dir, "IMPLEMENTATION.md")
                _safe_write(impl_path, impl_doc, emit, "IMPLEMENTATION.md")
            # Fallback: write README.md if push_key captured it but tool wasn't called
            readme_content = environments.get("readme")
            if readme_content:
                readme_path = os.path.join(game_dir, "README.md")
                if not os.path.exists(readme_path) or os.path.getsize(readme_path) == 0:
                    _safe_write(readme_path, readme_content, emit, "README.md")
            rounds_done = count_test_result_rounds(game_dir)
            early_exit = bool(attributes.get("_tests_passed"))
            emit("done", f"Game generation complete! ({rounds_done} test round(s), early_exit={early_exit})")
            return message

        post = graph.create_node(CustomNode, "post_processing")
        post.set_forward(post_proc)
        graph.create_edge(sender=build_body, receiver=post, keys={})
        graph.edge_to_exit(sender=post, keys={})

        _execute_graph(graph, environments, visualizer)

        if not environments.get("game_code"):
            environments["game_code"] = get_game_code()

        _capture_lessons(lesson_store, model, environments, game_dir, emit)

        return {
            "success": True,
            "game_dir": game_dir,
            "game_plan": environments.get("game_plan", ""),
            "test_checkpoints": environments.get("test_checkpoints", []),
            "game_code": environments.get("game_code", ""),
            "readme": environments.get("readme", ""),
            "ui_test_passed": environments.get("ui_test_passed"),
            "ui_test_report": environments.get("ui_test_report", ""),
            "functional_test_passed": environments.get("functional_test_passed"),
            "functional_test_report": environments.get("functional_test_report", ""),
            "html_validation": environments.get("html_validation"),
            "js_validation": environments.get("js_validation"),
            "browser_test_results": environments.get("browser_test_results"),
            "test_evidence": environments.get("test_evidence"),
            "structured_test_result": environments.get("structured_test_result"),
            "tests_passed_early": environments.get("_tests_passed", False),
            "error": None,
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        emit("error", f"Pipeline error: {e}")
        return {"success": False, "game_dir": game_dir, "error": str(e), "traceback": tb}


def run_modify_pipeline(
    session_id: str,
    task: str,
    modification_request: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    model_name: str = DEFAULT_MODEL,
    game_dir: str = None,
) -> dict:
    """
    Run the modification pipeline:
    IncrementalPlanning → Coding → [UITest → FuncTest → Fix] × 3 → Doc → post
    """
    games_dir = _games_dir()
    if game_dir is None:
        game_dir = os.path.join(games_dir, session_id)
    config_phase, config_role = load_configs()

    environments = {
        "config_phase": config_phase,
        "config_role": config_role,
        "session_id": session_id,
        "task": task,
        "modification_request": modification_request,
        "game_dir": game_dir,
        **_schema_contracts(),
        "game_plan": None,
        "game_code": None,
        "test_checkpoints": [],
        "readme": None,
        "human_design_feedback": "AUTO_APPROVED",
        "modification_context": "",
        "known_pitfalls": "",
        "learned_lessons": "",
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
        "discussion_finished": False,
        "_tests_passed": False,
    }

    def emit(stage, msg):
        logging.info(f"[{session_id}] [{stage}] {msg}")
        if progress_callback:
            progress_callback(stage, msg)

    rt = GameRuntimeContext(
        session_id=session_id,
        directory=game_dir,
        task=task,
        attributes=environments,
        progress_callback=emit,
    )
    set_game_runtime(rt)

    # Cross-session learning: surface known pitfalls from past games to Incremental Planning/Coding.
    lesson_store = LessonStore(_lessons_path(), api_key=api_key, base_url=base_url)
    environments["known_pitfalls"] = lesson_store.retrieve(f"{task} {modification_request}") or ""

    # Load existing game code and design
    environments["game_code"] = get_game_code()
    environments["modification_context"] = read_relevant_game_files_tool(modification_request, top_k=6)

    # Load design doc
    design_path = os.path.join(game_dir, "design.md")
    if os.path.exists(design_path):
        try:
            with open(design_path, "r", encoding="utf-8") as f:
                environments["game_plan"] = f.read()
        except Exception:
            pass

    # Load test_checkpoints
    checkpoints_path = os.path.join(game_dir, ".test_checkpoints.json")
    if os.path.exists(checkpoints_path):
        try:
            with open(checkpoints_path, "r", encoding="utf-8") as f:
                environments["test_checkpoints"] = json.load(f)
        except Exception:
            pass

    try:
        model = OpenAIModel(model_name=model_name, api_key=api_key, base_url=_normalize_base_url(base_url))
        visualizer = _connect_visualizer_trace(session_id, emit)
        environments["visualizer_trace"] = bool(visualizer)

        graph = RootGraph(name=f"browser_game_agent_modify_{session_id}", attributes=environments)

        def pre_proc(message, attributes):
            emit("planning", "Analyzing modification request...")
            return message

        pre = graph.create_node(CustomNode, "pre_proc")
        pre.set_forward(pre_proc)
        graph.edge_from_entry(receiver=pre, keys={})

        # --- build body (IncrementalPlanning → Coding → Test-Fix loop → Doc) ---
        build_body = graph.create_node(
            BrowserGameBuildGraph,
            name="build_body",
            mode="modify",
            config_phase=config_phase,
            config_role=config_role,
            model=model,
            rt=rt,
            emit=emit,
            game_dir=game_dir,
            max_rounds=MAX_TEST_ROUNDS,
            lesson_store=lesson_store,
        )
        graph.create_edge(sender=pre, receiver=build_body, keys={})

        def post_proc(message, attributes):
            for key in [
                "game_plan", "test_checkpoints", "game_code", "readme",
                "implementation_doc",
                "ui_test_passed", "ui_test_report", "ui_issues",
                "functional_test_passed", "functional_test_report", "functional_issues",
                "html_validation", "js_validation", "browser_test_results",
                "test_evidence", "structured_test_result", "modification_context",
                "_tests_passed",
            ]:
                val = attributes.get(key)
                if val is not None:
                    environments[key] = val
            if not environments.get("game_code"):
                environments["game_code"] = get_game_code()
            impl_doc = environments.get("implementation_doc")
            if impl_doc:
                impl_path = os.path.join(game_dir, "IMPLEMENTATION.md")
                _safe_write(impl_path, impl_doc, emit, "IMPLEMENTATION.md")
            # Update test_checkpoints on disk
            checkpoints = environments.get("test_checkpoints")
            if checkpoints:
                cp_path = os.path.join(game_dir, ".test_checkpoints.json")
                _safe_write(cp_path, json.dumps(checkpoints, ensure_ascii=False), emit, "test_checkpoints")
            # Fallback: write README.md if push_key captured it but tool wasn't called
            readme_content = environments.get("readme")
            if readme_content:
                readme_path = os.path.join(game_dir, "README.md")
                if not os.path.exists(readme_path) or os.path.getsize(readme_path) == 0:
                    _safe_write(readme_path, readme_content, emit, "README.md")
            emit("done", "Modification complete!")
            return message

        post = graph.create_node(CustomNode, "post")
        post.set_forward(post_proc)
        graph.create_edge(sender=build_body, receiver=post, keys={})
        graph.edge_to_exit(sender=post, keys={})

        _execute_graph(graph, environments, visualizer)

        if not environments.get("game_code"):
            environments["game_code"] = get_game_code()

        _capture_lessons(lesson_store, model, environments, game_dir, emit)

        return {
            "success": True,
            "game_dir": game_dir,
            "game_code": environments.get("game_code", ""),
            "ui_test_passed": environments.get("ui_test_passed"),
            "ui_test_report": environments.get("ui_test_report", ""),
            "functional_test_passed": environments.get("functional_test_passed"),
            "functional_test_report": environments.get("functional_test_report", ""),
            "html_validation": environments.get("html_validation"),
            "js_validation": environments.get("js_validation"),
            "browser_test_results": environments.get("browser_test_results"),
            "test_evidence": environments.get("test_evidence"),
            "structured_test_result": environments.get("structured_test_result"),
            "tests_passed_early": environments.get("_tests_passed", False),
            "error": None,
        }

    except Exception as e:
        import traceback
        emit("error", f"Modification error: {e}")
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


def run_ask_pipeline(
    session_id: str,
    task: str,
    user_question: str,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    model_name: str = DEFAULT_MODEL,
    game_dir: str = None,
) -> dict:
    """
    Run the analysis pipeline:
    pre(retrieve relevant files) → AnalysisPhase → post
    """
    games_dir = _games_dir()
    if game_dir is None:
        game_dir = os.path.join(games_dir, session_id)
    config_phase, config_role = load_configs()

    environments = {
        "config_phase": config_phase,
        "config_role": config_role,
        "session_id": session_id,
        "task": task,
        "user_question": user_question,
        "game_dir": game_dir,
        **_schema_contracts(),
        "all_game_files": None,
        "explanation": None,
        "discussion_finished": False,
    }

    def emit(stage, msg):
        logging.info(f"[{session_id}] [{stage}] {msg}")
        if progress_callback:
            progress_callback(stage, msg)

    rt = GameRuntimeContext(
        session_id=session_id,
        directory=game_dir,
        task=task,
        attributes=environments,
        progress_callback=emit,
    )
    set_game_runtime(rt)

    try:
        model = OpenAIModel(model_name=model_name, api_key=api_key, base_url=_normalize_base_url(base_url))
        visualizer = _connect_visualizer_trace(session_id, emit)
        environments["visualizer_trace"] = bool(visualizer)

        graph = RootGraph(name=f"browser_game_agent_ask_{session_id}", attributes=environments)

        # --- ask body (ContextLoad → Analysis) ---
        ask_body = graph.create_node(
            BrowserGameAskGraph,
            name="ask_body",
            config_phase=config_phase,
            config_role=config_role,
            model=model,
            rt=rt,
            emit=emit,
            game_dir=game_dir,
            user_question=user_question,
            top_k=6,
        )
        graph.edge_from_entry(receiver=ask_body, keys={})

        captured = {}

        def post_proc(message, attributes):
            expl = attributes.get("explanation")
            if expl:
                captured["explanation"] = expl
                environments["explanation"] = expl
            emit("done", "Analysis complete!")
            return message

        post = graph.create_node(CustomNode, "post")
        post.set_forward(post_proc)
        graph.create_edge(sender=ask_body, receiver=post, keys={})
        graph.edge_to_exit(sender=post, keys={})

        _execute_graph(graph, environments, visualizer)

        final_explanation = (
            captured.get("explanation")
            or environments.get("explanation")
            or (rt.attributes.get("explanation") if rt.attributes else None)
            or ""
        )

        return {
            "success": True,
            "explanation": final_explanation,
            "error": None,
        }

    except Exception as e:
        import traceback
        emit("error", f"Analysis error: {e}")
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
