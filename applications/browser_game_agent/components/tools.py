"""
Browser Game Agent Tools

Tools used by MASFactory phases to save and validate browser game files.
"""

from __future__ import annotations
import os
import re
import json
import time
import logging
import hashlib
import difflib

logger = logging.getLogger(__name__)
from pathlib import Path
from contextvars import ContextVar
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from applications.browser_game_agent.components.schemas import (
    BrowserCheckSchema,
    TestResultSchema,
    coerce_bool,
    model_to_dict,
)


@dataclass
class GameRuntimeContext:
    """Runtime context holding game session state"""
    session_id: str = ""
    directory: str = ""
    task: str = ""
    game_plan: str = ""
    game_code: str = ""
    readme: str = ""
    ui_test_passed: bool = False
    ui_test_report: str = ""
    ui_issues: list = field(default_factory=list)
    functional_test_passed: bool = False
    functional_test_report: str = ""
    functional_issues: list = field(default_factory=list)
    attributes: dict = None
    progress_callback: Any = None  # callable(stage: str, message: str)


_RUNTIME_CONTEXT: ContextVar[Optional[GameRuntimeContext]] = ContextVar(
    "browser_game_agent_runtime",
    default=None,
)


def set_game_runtime(context: GameRuntimeContext) -> None:
    """Register runtime context for the current execution context."""
    _RUNTIME_CONTEXT.set(context)


def get_game_runtime() -> GameRuntimeContext:
    runtime = _RUNTIME_CONTEXT.get()
    if runtime is None:
        raise RuntimeError("GameRuntimeContext not set. Call set_game_runtime() first.")
    return runtime


def emit_progress(stage: str, message: str) -> None:
    """Send progress update through the callback if available."""
    rt = get_game_runtime()
    if rt.progress_callback:
        rt.progress_callback(stage, message)


def _human_review_enabled() -> bool:
    return os.getenv("BGA_ENABLE_HUMAN_REVIEW", "").strip().lower() in {"1", "true", "yes", "on"}


def _confirm_overwrite_with_visualizer(path: Path, new_content: str) -> tuple[bool, str]:
    if not _human_review_enabled() or not path.exists():
        return True, "human review disabled"
    try:
        old_content = path.read_text(encoding="utf-8")
    except Exception:
        old_content = ""
    if old_content == new_content:
        return True, "unchanged"

    draft_path = path.with_name(f".{path.name}.draft")
    try:
        draft_path.write_text(new_content, encoding="utf-8")
    except Exception:
        pass
    diff = "\n".join(
        difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=str(path),
            tofile=str(draft_path),
            lineterm="",
        )
    )
    if len(diff) > 12000:
        diff = diff[:12000] + "\n...(diff truncated)"
    try:
        from masfactory.visualizer import VisualizerOpenFileOptions, connect

        visualizer = connect(timeout_s=0.5)
        if visualizer is None:
            return False, "human review enabled but MASFactory Visualizer is unavailable"
        try:
            visualizer.open_file(VisualizerOpenFileOptions(file_path=str(draft_path), view="preview", reveal=True))
        except Exception:
            pass
        response = visualizer.request_user_input(
            node="browser_game_agent_file_review",
            field="overwrite_confirmation",
            description=f"Confirm overwrite for {path.name}",
            prompt=(
                f"Review the generated draft before overwriting {path.name}.\n\n"
                f"Unified diff:\n{diff}\n\n"
                "Reply APPROVE to overwrite the original file. Any other response cancels this write."
            ),
            timeout_s=None,
            meta={"kind": "file_overwrite_review", "target": str(path), "draft": str(draft_path)},
        )
        approved = isinstance(response, str) and response.strip().upper().startswith("APPROVE")
        return approved, "approved by human" if approved else "not approved by human"
    except Exception as exc:
        return False, f"human review failed: {exc}"


def _runtime_dir() -> Path:
    rt = get_game_runtime()
    if not rt.directory:
        raise RuntimeError("game directory not set in runtime context")
    root = Path(rt.directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_output_path(filename: str) -> Path:
    root = _runtime_dir()
    clean = str(filename or "").strip().replace("\\", "/")
    if not clean or clean.startswith("/") or clean.startswith("../") or "/../" in clean:
        raise ValueError(f"Unsafe output filename: {filename!r}")
    path = (root / clean).resolve()
    if root != path and root not in path.parents:
        raise ValueError(f"Output path escapes game directory: {filename!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except Exception:
        return {"raw": text}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def save_game_files_tool(files: List[Dict[str, str]]) -> str:
    """
    Save browser game files to the session output directory.

    Args:
        files: List of dicts with 'filename' and 'content' keys.
               Example: [{"filename": "index.html", "content": "<!DOCTYPE html>..."}]

    Returns:
        str: Status message.
    """
    try:
        rt = get_game_runtime()
        if not rt.directory:
            return "Error: game directory not set in runtime context"

        saved = []
        game_code_parts = []

        for file_dict in files:
            filename = file_dict.get("filename", "").strip()
            content = file_dict.get("content", "")
            if not filename:
                continue
            filepath = _safe_output_path(filename)
            approved, review_msg = _confirm_overwrite_with_visualizer(filepath, content)
            if not approved:
                emit_progress("deploy", f"Human review blocked overwrite of {filename}: {review_msg}")
                return f"Human review blocked overwrite of {filename}: {review_msg}"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            saved.append(filename)
            if filename.endswith(".html"):
                game_code_parts.append(f"=== {filename} ===\n{content}")
            elif filename.endswith((".js", ".css")):
                game_code_parts.append(f"=== {filename} ===\n{content}")

        # Cache game_code in runtime and attributes
        if game_code_parts:
            rt.game_code = "\n\n".join(game_code_parts)
            if rt.attributes is not None:
                rt.attributes["game_code"] = rt.game_code

        emit_progress("deploy", f"Saved {len(saved)} game file(s): {', '.join(saved)}")
        return f"Successfully saved {len(saved)} file(s) to {rt.directory}: {', '.join(saved)}"

    except Exception as e:
        import traceback
        return f"Error saving files: {e}\n{traceback.format_exc()}"


def save_readme_tool(content: str) -> str:
    """
    Save README.md to the game session directory.

    Args:
        content: Markdown content for README.md

    Returns:
        str: Status message.
    """
    try:
        rt = get_game_runtime()
        if not rt.directory:
            return "Error: game directory not set"

        path = _safe_output_path("README.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        rt.readme = content
        if rt.attributes is not None:
            rt.attributes["readme"] = content

        return "Saved README.md successfully."
    except Exception as e:
        return f"Error saving README: {e}"


def validate_html_structure_tool() -> str:
    """
    Validate HTML structure of the generated game.
    Checks for basic HTML5 structure and script presence.

    Returns:
        str: JSON result with validation details.
    """
    try:
        rt = get_game_runtime()
        index_path = os.path.join(rt.directory, "index.html")
        if not os.path.exists(index_path):
            return json.dumps({
                "valid": False,
                "issues": ["index.html not found"],
                "details": "Game file does not exist"
            })

        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Also load external JS/CSS files for game loop detection
        all_code = html
        if rt.directory and os.path.exists(rt.directory):
            for fname in os.listdir(rt.directory):
                if fname.endswith((".js", ".css")) and not fname.startswith("."):
                    try:
                        with open(os.path.join(rt.directory, fname), "r", encoding="utf-8") as f:
                            all_code += "\n" + f.read()
                    except Exception as exc:
                        logger.warning("get_game_code: skipped unreadable %s: %s", fname, exc)

        issues = []
        warnings = []

        # Critical: must have DOCTYPE
        if "<!doctype" not in html.lower():
            issues.append("Missing HTML5 doctype declaration")

        # Critical: must have script (either inline or external .js file)
        has_script = "<script" in html.lower()
        has_js_file = any(f.endswith(".js") for f in os.listdir(rt.directory) if not f.startswith("."))
        if not has_script and not has_js_file:
            issues.append("No JavaScript found - game needs scripts to run")

        # Warning only: game loop pattern
        if "requestanimationframe" not in all_code.lower() and "setinterval" not in all_code.lower():
            warnings.append("No explicit game loop pattern found (requestAnimationFrame/setInterval) - may use event-driven approach")

        result = {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "html_size": len(html),
            "details": "HTML structure validation complete"
        }
        if rt.attributes is not None:
            rt.attributes["html_validation"] = _json_dumps(result)
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"valid": False, "issues": [str(e)], "details": "Validation error"})


def validate_js_logic_tool() -> str:
    """
    Validate JavaScript game logic in the generated game.
    Checks for game loop and event handlers.

    Returns:
        str: JSON result with validation details.
    """
    try:
        rt = get_game_runtime()
        index_path = os.path.join(rt.directory, "index.html")
        if not os.path.exists(index_path):
            return json.dumps({
                "valid": False,
                "issues": ["index.html not found"],
                "details": "Game file does not exist"
            })

        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Extract inline JS content
        js_matches = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
        js_content = "\n".join(js_matches)

        # Also include external .js files
        if rt.directory and os.path.exists(rt.directory):
            for fname in sorted(os.listdir(rt.directory)):
                if fname.endswith(".js") and not fname.startswith("."):
                    try:
                        with open(os.path.join(rt.directory, fname), "r", encoding="utf-8") as f:
                            js_content += "\n" + f.read()
                    except Exception as exc:
                        logger.warning("validate_js_logic: skipped unreadable %s: %s", fname, exc)

        js_lower = js_content.lower()
        issues = []
        warnings = []

        # Critical: must have some form of game loop or event-driven updates
        has_loop = "requestanimationframe" in js_lower or "setinterval" in js_lower or "settimeout" in js_lower
        has_events = "addeventlistener" in js_lower or "onkeydown" in js_lower or "onclick" in js_lower or "onmousedown" in js_lower
        if not has_loop and not has_events:
            issues.append("No game loop or event handlers found - game has no interactivity")

        # Warning: no input handlers
        if not has_events:
            warnings.append("No input event handlers found (may use inline handlers)")

        # Warning: no score tracking (not all games need it)
        if "score" not in js_lower and "point" not in js_lower and "count" not in js_lower:
            warnings.append("No score/point tracking found (acceptable for some game types)")

        result = {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "js_lines": len(js_content.split("\n")),
            "details": "JavaScript logic validation complete"
        }
        if rt.attributes is not None:
            rt.attributes["js_validation"] = _json_dumps(result)
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"valid": False, "issues": [str(e)], "details": "Validation error"})


def run_browser_smoke_test_tool(round_num: int = 1, wait_ms: int = 700) -> str:
    """
    Execute a real headless browser smoke test against index.html.

    Checks page load, console/page errors, canvas presence, nonblank pixels,
    keyboard dispatch, and whether the rendered screenshot changes after input.
    Requires the optional `playwright` package and installed browser binaries.
    """
    rt = get_game_runtime()
    issues: list[str] = []
    warnings: list[str] = []
    result = BrowserCheckSchema(
        available=False,
        details="Playwright did not run.",
    )

    index_path = Path(rt.directory or "") / "index.html"
    if not index_path.exists():
        issues.append("index.html not found")
        result.issues = issues
        payload = model_to_dict(result)
        if rt.attributes is not None:
            rt.attributes["browser_test_results"] = _json_dumps(payload)
        return _json_dumps(payload)

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        warnings.append(
            "Playwright is not installed or browser binaries are missing. "
            "Install with `pip install playwright` and run `python -m playwright install chromium`."
        )
        result.warnings = warnings
        result.details = f"Playwright unavailable: {exc}"
        payload = model_to_dict(result)
        if rt.attributes is not None:
            rt.attributes["browser_test_results"] = _json_dumps(payload)
        return _json_dumps(payload)

    console_errors: list[str] = []
    page_errors: list[str] = []
    screenshot_path = str(Path(rt.directory) / f".browser_smoke_round_{round_num}.png")

    def _hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 960, "height": 720})
            page.on(
                "console",
                lambda msg: console_errors.append(msg.text)
                if msg.type in {"error", "warning"}
                else None,
            )
            page.on("pageerror", lambda err: page_errors.append(str(err)))
            page.goto(index_path.resolve().as_uri(), wait_until="domcontentloaded", timeout=5000)
            page.wait_for_timeout(max(100, int(wait_ms)))

            viewport = page.viewport_size or {"width": 960, "height": 720}
            page.mouse.click(viewport["width"] / 2, viewport["height"] / 2)
            page.wait_for_timeout(250)

            canvas_info = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('canvas')).map((canvas) => {
                    const rect = canvas.getBoundingClientRect();
                    let nonblank = false;
                    let sampleError = "";
                    try {
                        const ctx = canvas.getContext('2d');
                        if (ctx && canvas.width > 0 && canvas.height > 0) {
                            const w = Math.min(canvas.width, 80);
                            const h = Math.min(canvas.height, 80);
                            const data = ctx.getImageData(0, 0, w, h).data;
                            for (let i = 0; i < data.length; i += 4) {
                                if (data[i] || data[i + 1] || data[i + 2] || data[i + 3]) {
                                    nonblank = true;
                                    break;
                                }
                            }
                        }
                    } catch (err) {
                        sampleError = String(err);
                    }
                    return {
                        width: canvas.width,
                        height: canvas.height,
                        cssWidth: rect.width,
                        cssHeight: rect.height,
                        nonblank,
                        sampleError
                    };
                })
                """
            )

            before = page.screenshot(full_page=True)
            dispatched = 0
            for key in ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Space"]:
                try:
                    page.keyboard.press(key)
                    dispatched += 1
                    page.wait_for_timeout(100)
                except Exception as exc:
                    warnings.append(f"Keyboard dispatch failed for {key}: {exc}")
            page.wait_for_timeout(max(250, int(wait_ms)))
            after = page.screenshot(path=screenshot_path, full_page=True)
            browser.close()

        canvas_count = len(canvas_info)
        canvas_nonblank = any(bool(item.get("nonblank")) for item in canvas_info)
        screenshot_changed = _hash(before) != _hash(after)

        if console_errors:
            issues.extend([f"Console: {msg}" for msg in console_errors[:8]])
        if page_errors:
            issues.extend([f"Page error: {msg}" for msg in page_errors[:8]])
        if canvas_count == 0:
            issues.append("No canvas element found during browser smoke test")
        elif not canvas_nonblank:
            issues.append("Canvas appears blank in sampled pixels")
        if dispatched == 0:
            issues.append("No keyboard events were dispatched")
        if not screenshot_changed:
            warnings.append("Screenshot did not change after click/keyboard input; game may be static or waiting for a different start interaction")

        result = BrowserCheckSchema(
            available=True,
            page_loaded=True,
            console_errors=console_errors,
            page_errors=page_errors,
            canvas_count=canvas_count,
            canvas_nonblank=canvas_nonblank,
            screenshot_changed_after_input=screenshot_changed,
            keyboard_events_dispatched=dispatched,
            screenshot_path=screenshot_path,
            issues=issues,
            warnings=warnings,
            details="Browser smoke test complete",
        )
    except Exception as exc:
        issues.append(str(exc))
        result = BrowserCheckSchema(
            available=False,
            page_loaded=False,
            console_errors=console_errors,
            page_errors=page_errors,
            canvas_count=0,
            canvas_nonblank=False,
            screenshot_changed_after_input=False,
            keyboard_events_dispatched=0,
            screenshot_path=screenshot_path if os.path.exists(screenshot_path) else "",
            issues=issues,
            warnings=warnings,
            details="Browser smoke test failed before completion",
        )

    payload = model_to_dict(result)
    if rt.attributes is not None:
        rt.attributes["browser_test_results"] = _json_dumps(payload)
    return _json_dumps(payload)


def get_game_code() -> str:
    """Return the current game code from runtime context, including all relevant files."""
    rt = get_game_runtime()
    if rt.game_code:
        return rt.game_code
    # Try reading all relevant files from disk
    if not rt.directory or not os.path.exists(rt.directory):
        return ""
    parts = []
    # Read index.html first (entry point), then other files
    priority_files = ["index.html"]
    all_files = sorted(os.listdir(rt.directory))
    ordered = priority_files + [f for f in all_files if f not in priority_files]
    for filename in ordered:
        filepath = os.path.join(rt.directory, filename)
        if not os.path.isfile(filepath):
            continue
        if filename.startswith("."):  # skip hidden files like .test_checkpoints.json
            continue
        if filename.endswith((".html", ".js", ".css", ".md")):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                parts.append(f"=== {filename} ===\n{content}")
            except Exception as exc:
                logger.warning("read_all_game_files: skipped unreadable %s: %s", filename, exc)
    if parts:
        rt.game_code = "\n\n".join(parts)
        return rt.game_code
    return ""


def set_explanation_tool(content: str) -> str:
    """
    Save the explanation/answer to be returned to the user.

    Args:
        content: The explanation text answering the user's question.

    Returns:
        str: Confirmation message.
    """
    try:
        rt = get_game_runtime()
        rt.game_code  # just access to ensure runtime is set
        if rt.attributes is not None:
            rt.attributes["explanation"] = content
        return "Explanation saved successfully."
    except Exception as e:
        return f"Error: {e}"


def save_design_doc_tool(content: str) -> str:
    """
    Save design.md to the game session directory.

    Args:
        content: Markdown content for the design document.

    Returns:
        str: Status message.
    """
    try:
        rt = get_game_runtime()
        if not rt.directory:
            return "Error: game directory not set"
        path = _safe_output_path("design.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        if rt.attributes is not None:
            rt.attributes["game_plan"] = content
        rt.game_plan = content
        emit_progress("planning", "Design document saved to design.md")
        return "Saved design.md successfully."
    except Exception as e:
        return f"Error saving design doc: {e}"


def save_test_results_tool(
    round_num: int,
    ui_passed: bool,
    func_passed: bool,
    ui_issues: List[str],
    functional_issues: List[str],
    ui_report: str = "",
    functional_report: str = "",
    evidence: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Append test results for a given round to test_results.json.

    Args:
        round_num: Test round number (1, 2, or 3).
        ui_passed: Whether the UI test passed.
        func_passed: Whether the functional test passed.
        ui_issues: List of UI issue strings.
        functional_issues: List of functional issue strings.

    Returns:
        str: Status message.
    """
    try:
        rt = get_game_runtime()
        if not rt.directory:
            return "Error: game directory not set"
        results_path = _safe_output_path("test_results.json")

        # Load existing results or start fresh. Older sessions stored a bare
        # list; keep reading that shape while writing the richer envelope.
        if os.path.exists(results_path):
            with open(results_path, "r", encoding="utf-8") as f:
                existing_results = json.load(f)
        else:
            existing_results = {}
        if isinstance(existing_results, list):
            all_results = existing_results
        elif isinstance(existing_results, dict):
            all_results = list(existing_results.get("rounds") or [])
        else:
            all_results = []

        normalized = TestResultSchema(
            round=int(round_num),
            ui_passed=coerce_bool(ui_passed),
            func_passed=coerce_bool(func_passed),
            both_passed=coerce_bool(ui_passed) and coerce_bool(func_passed),
            ui_issues=list(ui_issues or []),
            functional_issues=list(functional_issues or []),
            ui_report=str(ui_report or ""),
            functional_report=str(functional_report or ""),
            evidence=dict(evidence or {}),
        )
        round_result = model_to_dict(normalized)
        # Replace existing entry for this round if present.
        round_key = int(round_num)
        def _is_other_round(item: Any) -> bool:
            if not isinstance(item, dict):
                return False
            try:
                return int(item.get("round", -1)) != round_key
            except Exception:
                return True

        all_results = [r for r in all_results if _is_other_round(r)]
        all_results.append(round_result)
        all_results.sort(key=lambda r: r.get("round", 0))

        output = {
            "schema": "browser_game_agent.test_results.v1",
            "session_id": rt.session_id,
            "task": rt.task,
            "rounds": all_results,
            "latest": round_result,
            "passed": normalized.both_passed,
        }
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        # Update runtime state
        rt.ui_test_passed = normalized.ui_passed
        rt.functional_test_passed = normalized.func_passed
        rt.ui_test_report = normalized.ui_report
        rt.functional_test_report = normalized.functional_report
        rt.ui_issues = normalized.ui_issues
        rt.functional_issues = normalized.functional_issues
        if rt.attributes is not None:
            rt.attributes["_tests_passed"] = normalized.both_passed
            rt.attributes["ui_test_passed"] = normalized.ui_passed
            rt.attributes["functional_test_passed"] = normalized.func_passed
            rt.attributes["ui_test_report"] = normalized.ui_report
            rt.attributes["functional_test_report"] = normalized.functional_report
            rt.attributes["ui_issues"] = normalized.ui_issues
            rt.attributes["functional_issues"] = normalized.functional_issues
            rt.attributes["structured_test_result"] = round_result

        status = "PASS" if normalized.both_passed else "FAIL"
        return f"Test results for round {round_num} saved ({status}). UI: {'PASS' if normalized.ui_passed else 'FAIL'}, Functional: {'PASS' if normalized.func_passed else 'FAIL'}."
    except Exception as e:
        return f"Error saving test results: {e}"


def read_all_game_files_tool() -> str:
    """
    Read all output files from the game session directory and return combined content.
    Includes design.md, game source files, test_results.json, IMPLEMENTATION.md, README.md.

    Returns:
        str: Combined content of all output files.
    """
    try:
        rt = get_game_runtime()
        if not rt.directory or not os.path.exists(rt.directory):
            return "Error: game directory not set or does not exist"

        parts = []
        # Priority order for reading
        priority_order = [
            "design.md",
            "index.html",
            "game.js",
            "style.css",
            "test_results.json",
            "IMPLEMENTATION.md",
            "README.md",
        ]
        all_files = sorted(os.listdir(rt.directory))
        ordered = priority_order + [f for f in all_files if f not in priority_order]

        for filename in ordered:
            filepath = os.path.join(rt.directory, filename)
            if not os.path.isfile(filepath):
                continue
            if filename.startswith("."):
                continue
            if filename.endswith((".html", ".js", ".css", ".md", ".json")):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    parts.append(f"=== {filename} ===\n{content}")
                except Exception as exc:
                    logger.warning("read_relevant_game_files: skipped unreadable %s: %s", filename, exc)

        if not parts:
            return "No output files found in the game directory."
        return "\n\n".join(parts)
    except Exception as e:
        return f"Error reading game files: {e}"


def read_relevant_game_files_tool(query: str, top_k: int = 6) -> str:
    """
    Retrieve the most relevant output files for a question or modification request.

    Delegates to the shared retrieve_session_context helper, which uses MASFactory's
    SimpleKeywordRetriever over the current session artifacts, keeping ask/modify prompts
    grounded without blindly injecting every file.
    """
    try:
        from applications.browser_game_agent.components.retrieval import retrieve_session_context

        rt = get_game_runtime()
        return retrieve_session_context(query, top_k=top_k, directory=rt.directory)
    except Exception as e:
        return f"Error retrieving game files: {e}"


__all__ = [
    "GameRuntimeContext",
    "set_game_runtime",
    "get_game_runtime",
    "emit_progress",
    "save_game_files_tool",
    "save_readme_tool",
    "validate_html_structure_tool",
    "validate_js_logic_tool",
    "get_game_code",
    "set_explanation_tool",
    "save_design_doc_tool",
    "save_test_results_tool",
    "read_all_game_files_tool",
    "read_relevant_game_files_tool",
    "run_browser_smoke_test_tool",
]
