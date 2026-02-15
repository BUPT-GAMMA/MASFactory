"""
Utility tools for the MetaGPT software company pipeline running on the MASFactory framework.

These tools take inspiration from the MetaGPT engineer2 Toolkit (Editor, Terminal, CodeReview),
but are reimplemented as simple Python functions to comply with the current MASFactory tool API:

    - Each tool is a plain callable with type hints.
    - Docstrings describe parameters and return values (JsonSchema generation relies on them).
    - Tools return human-readable strings so that LLMs can reason on the results.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from collections import Counter
from typing import List, Optional


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def read_project_file(file_path: str, max_lines: int = 800) -> str:
    """
    Read a text file and return its content with line numbers.

    Args:
        file_path: Absolute or relative path to the file.
        max_lines: Maximum lines allowed to avoid dumping huge files (default 800).

    Returns:
        Content string with line numbers like "001|from foo import bar".
        If file cannot be read or exceeds the limit, returns an error message.
    """
    path = Path(file_path).expanduser()
    if not path.exists():
        return f"[read_project_file] Error: '{file_path}' does not exist."
    if not path.is_file():
        return f"[read_project_file] Error: '{file_path}' is not a regular file."

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"[read_project_file] Error: '{file_path}' is not a UTF-8 text file."

    lines = content.splitlines()
    if len(lines) > max_lines:
        return (
            f"[read_project_file] Error: '{file_path}' has {len(lines)} lines, "
            f"exceeding limit {max_lines}. Please open a smaller section."
        )

    numbered = [f"{i+1:03d}|{line}" for i, line in enumerate(lines)]
    header = f"[File: {path.resolve()} ({len(lines)} lines)]"
    return header + "\n" + "\n".join(numbered)


def write_project_file(file_path: str, content: str, **_: object) -> str:
    """
    Overwrite a file with the provided content (creating parents if necessary).

    Args:
        file_path: Absolute or relative path to the target file.
        content: The full text to write into the file.

    Returns:
        Status message with absolute file path and total line count written.
    """
    path = Path(file_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    line_count = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
    return f"[write_project_file] Saved {line_count} lines to '{path.resolve()}'"


def list_project_files(directory_path: str, glob_pattern: str = "*", recursive: bool = True) -> str:
    """
    List files under a directory using a glob pattern.

    Args:
        directory_path: Directory to scan.
        glob_pattern: Glob expression, e.g. "*.py" or "src/**/*.ts".
        recursive: Whether to search recursively (default True).

    Returns:
        A newline separated list of matched files relative to the directory.
    """
    base = Path(directory_path).expanduser()
    if not base.exists():
        return f"[list_project_files] Error: directory '{directory_path}' does not exist."
    if not base.is_dir():
        return f"[list_project_files] Error: '{directory_path}' is not a directory."

    pattern = glob_pattern
    if recursive and "**" not in pattern:
        pattern = f"**/{pattern}"

    files = sorted(p.relative_to(base) for p in base.glob(pattern) if p.is_file())
    if not files:
        return f"[list_project_files] No files matched '{glob_pattern}' under '{directory_path}'."

    header = f"[list_project_files] Found {len(files)} file(s) under '{directory_path}' matching '{glob_pattern}':"
    return header + "\n" + "\n".join(str(p) for p in files)


def search_in_project_file(file_path: str, keyword: str, context_lines: int = 2) -> str:
    """
    Search for a keyword inside a file and show matches with context.

    Args:
        file_path: Path to the file to search.
        keyword: Plain substring to look for (case-sensitive).
        context_lines: Number of lines before/after each match to include.

    Returns:
        Human-readable search result. Warns if no matches found.
    """
    path = Path(file_path).expanduser()
    if not path.exists():
        return f"[search_in_project_file] Error: '{file_path}' not found."
    if not path.is_file():
        return f"[search_in_project_file] Error: '{file_path}' is not a file."

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return f"[search_in_project_file] Error: '{file_path}' is not a UTF-8 text file."

    matches = [idx for idx, line in enumerate(lines) if keyword in line]
    if not matches:
        return f"[search_in_project_file] No occurrences of '{keyword}' found in '{file_path}'."

    chunks: List[str] = [f"[search_in_project_file] Found {len(matches)} occurrence(s) of '{keyword}':"]
    for idx in matches:
        start = max(0, idx - context_lines)
        end = min(len(lines), idx + context_lines + 1)
        chunks.append(f"\nLine {idx+1}:")
        for line_no in range(start, end):
            prefix = ">>>" if line_no == idx else "   "
            chunks.append(f"{prefix} {line_no+1:03d}|{lines[line_no]}")
    return "\n".join(chunks)


def check_project_path(path_str: str) -> str:
    """
    Check if a path exists and report its type.

    Args:
        path_str: Absolute or relative path to inspect.

    Returns:
        Message describing whether the path exists and if it is a file or directory.
    """
    path = Path(path_str).expanduser()
    if not path.exists():
        return f"[check_project_path] '{path_str}' does not exist."
    if path.is_file():
        return f"[check_project_path] '{path_str}' exists (file, {path.stat().st_size} bytes)."
    if path.is_dir():
        try:
            count = len(list(path.iterdir()))
        except PermissionError:
            count = -1
        item_msg = f", {count} items" if count >= 0 else ""
        return f"[check_project_path] '{path_str}' exists (directory{item_msg})."
    return f"[check_project_path] '{path_str}' exists (special path)."


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

def run_project_command(command: str, timeout: int = 30) -> str:
    """
    Execute a shell command in the current working directory.

    Args:
        command: Shell command to run, e.g. "python main.py".
        timeout: Maximum seconds to wait before aborting (default 30).

    Returns:
        Combined stdout/stderr along with the exit status.
    """
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd(),
        )
    except subprocess.TimeoutExpired:
        return f"[run_project_command] Error: command timed out after {timeout}s."
    except Exception as exc:
        return f"[run_project_command] Error executing command: {exc}"

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    output_lines = [f"[run_project_command] exit_code={completed.returncode}"]
    if stdout:
        output_lines.append("STDOUT:\n" + stdout)
    if stderr:
        output_lines.append("STDERR:\n" + stderr)
    if not stdout and not stderr:
        output_lines.append("(no output)")
    return "\n".join(output_lines)


def summarize_python_file(file_path: str) -> str:
    """
    Summarize top-level classes and functions within a Python file.

    Args:
        file_path: Path to the Python source file.

    Returns:
        Summary describing classes/functions and their docstrings.
    """
    path = Path(file_path).expanduser()
    if not path.exists():
        return f"[summarize_python_file] Error: '{file_path}' does not exist."
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"[summarize_python_file] Error: '{file_path}' is not a UTF-8 text file."

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"[summarize_python_file] Error: cannot parse '{file_path}': {exc}"

    sections: List[str] = [f"[summarize_python_file] Summary for {path}:"]
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or "(no docstring)"
            sections.append(f"- class {node.name}: {doc}")
            methods = [
                n.name for n in node.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
            ]
            if methods:
                sections.append(f"  public methods: {', '.join(methods)}")
        elif isinstance(node, ast.FunctionDef):
            doc = ast.get_docstring(node) or "(no docstring)"
            sections.append(f"- def {node.name}(): {doc}")
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Code-quality helpers
# ---------------------------------------------------------------------------

def run_python_linter(file_path: str, config_path: Optional[str] = None, max_output: int = 4000) -> str:
    """
    Run flake8 (preferred) or pylint as a fallback on a Python file.

    Args:
        file_path: Python file to lint.
        config_path: Optional path to a config file passed to the linter.
        max_output: Maximum characters returned (truncate overly long logs).

    Returns:
        Linter output or message indicating success/failure.
    """
    path = Path(file_path).expanduser()
    if not path.exists():
        return f"[run_python_linter] Error: '{file_path}' does not exist."

    def _exec(cmd: List[str]) -> Optional[str]:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=os.getcwd())
        except FileNotFoundError:
            return None
        except Exception as exc:  # pragma: no cover - defensive
            return f"[run_python_linter] Error running {' '.join(cmd)}: {exc}"
        output = (res.stdout + "\n" + res.stderr).strip()
        if len(output) > max_output:
            output = output[: max_output - 100] + "\n... (truncated)"
        if res.returncode == 0:
            return output or "[run_python_linter] Success: no issues found."
        return output or "[run_python_linter] Completed with diagnostics."

    base_cmd = ["flake8", str(path)]
    if config_path:
        base_cmd.extend(["--config", str(Path(config_path).expanduser())])
    result = _exec(base_cmd)
    if result is not None:
        return result

    pylint_cmd = ["pylint", str(path)]
    if config_path:
        pylint_cmd.extend(["--rcfile", str(Path(config_path).expanduser())])
    result = _exec(pylint_cmd)
    if result is not None:
        return result

    return "[run_python_linter] Neither flake8 nor pylint is available in the environment."


# ---------------------------------------------------------------------------
# Product management helpers
# ---------------------------------------------------------------------------

STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "your",
    "user",
    "users",
    "project",
    "system",
    "application",
}


def extract_requirement_keywords(requirement_text: str, top_n: int = 6) -> str:
    """
    Extract top keywords from the raw requirement text.

    Args:
        requirement_text: Free-form requirement description.
        top_n: Maximum number of keywords to return.

    Returns:
        Ranked keyword list with simple heuristics.
    """
    words = [w.strip(".,:;!?()[]{}").lower() for w in requirement_text.split()]
    filtered = [w for w in words if w and len(w) > 2 and w not in STOP_WORDS]
    counts = Counter(filtered)
    common = counts.most_common(top_n)
    if not common:
        return "[extract_requirement_keywords] No keywords extracted."
    lines = [f"- {word} (score {freq})" for word, freq in common]
    return "[extract_requirement_keywords] Top terms:\n" + "\n".join(lines)


def draft_competitor_brief(product_theme: str, competitor_count: int = 3) -> str:
    """
    Produce a lightweight competitor analysis scaffold for PRD writing.

    Args:
        product_theme: Theme or feature keywords (comma separated).
        competitor_count: Number of competitor slots to include.

    Returns:
        Bullet list describing hypothetical competitors and gaps.
    """
    keywords = [kw.strip() for kw in product_theme.split(",") if kw.strip()]
    base = keywords[:2] or ["core feature"]
    entries = []
    for idx in range(competitor_count):
        focus = base[idx % len(base)]
        entries.append(
            f"- Competitor {idx + 1}: Strength in {focus}; lacks differentiated UX and automation."
        )
    return "[draft_competitor_brief]\n" + "\n".join(entries)


def summarize_user_personas(requirement_text: str) -> str:
    """
    Infer 2-3 user personas from the requirement description.

    Args:
        requirement_text: Requirement text or PRD notes.

    Returns:
        Persona list with goals/pain points.
    """
    sentences = [s.strip() for s in requirement_text.replace("\n", " ").split(".") if s.strip()]
    personas = []
    for idx, sentence in enumerate(sentences[:3]):
        personas.append(
            f"- Persona {idx + 1}: Needs {sentence[:120]}...; Goal: accomplish this flow without friction."
        )
    if not personas:
        personas = ["- Persona 1: Prospective end-user; Goal: achieve task quickly."]
    return "[summarize_user_personas]\n" + "\n".join(personas)


# ---------------------------------------------------------------------------
# Architecture helpers
# ---------------------------------------------------------------------------

def propose_file_breakdown(prd_summary: str, tech_stack: str = "python") -> str:
    """
    Suggest a file/module breakdown based on PRD highlights.

    Args:
        prd_summary: Short PRD paragraph or bullet list.
        tech_stack: Programming language or framework keyword.

    Returns:
        Suggested file list grouped by tiers.
    """
    base_files = ["main", "services", "models", "api", "ui"]
    suffix = ".py" if "py" in tech_stack.lower() else ".js"
    lines = [f"[propose_file_breakdown] Recommended files for {tech_stack}:"]
    for name in base_files:
        lines.append(f"- {name}{suffix}")
    if "dashboard" in prd_summary.lower():
        lines.append("- ui/dashboard" + suffix)
    if "auth" in prd_summary.lower():
        lines.append("- auth/token_handler" + suffix)
    return "\n".join(lines)


def recommend_architecture_pattern(prd_summary: str) -> str:
    """
    Recommend a high-level architecture style (monolith, layered, event-driven, etc.).

    Args:
        prd_summary: Key requirement points.

    Returns:
        Textual recommendation with rationale.
    """
    summary_lower = prd_summary.lower()
    if any(kw in summary_lower for kw in ("real-time", "stream", "event")):
        style = "event-driven"
        reasoning = "real-time streaming requirements detected."
    elif any(kw in summary_lower for kw in ("microservice", "scale", "multi-tenant")):
        style = "microservice"
        reasoning = "scalability and team parallelism hinted."
    else:
        style = "layered monolith"
        reasoning = "default choice for typical SaaS MVP scope."
    return f"[recommend_architecture_pattern] Suggest {style} architecture because {reasoning}"


def validate_mermaid_snippet(diagram_text: str) -> str:
    """
    Perform lightweight validation of a Mermaid diagram snippet.

    Args:
        diagram_text: Mermaid code to verify.

    Returns:
        Checklist covering classDiagram/sequenceDiagram presence and braces.
    """
    text = diagram_text.strip()
    summary = ["[validate_mermaid_snippet]"]
    if "classDiagram" in text:
        summary.append("- Contains classDiagram block.")
    if "sequenceDiagram" in text:
        summary.append("- Contains sequenceDiagram block.")
    if text.count("{") == text.count("}"):
        summary.append("- Balanced braces detected.")
    else:
        summary.append("- Warning: braces seem unbalanced.")
    if "(" in text or ")" in text:
        if text.count("(") == text.count(")"):
            summary.append("- Parentheses count OK.")
        else:
            summary.append("- Warning: parentheses mismatch.")
    return "\n".join(summary)


# ---------------------------------------------------------------------------
# Project management helpers
# ---------------------------------------------------------------------------

def analyze_task_dependencies(task_lines: List[str]) -> str:
    """
    Build a simple dependency summary from textual task descriptions.

    Args:
        task_lines: List of task sentences or filenames.

    Returns:
        Ordered summary highlighting which items should precede others.
    """
    ordering = []
    seen_main = False
    for line in task_lines:
        normalized = line.lower()
        if "main" in normalized and not seen_main:
            ordering.append(f"- {line} (ENTRY POINT: schedule last to integrate modules)")
            seen_main = True
        elif any(keyword in normalized for keyword in ("api", "service", "model")):
            ordering.append(f"- {line} (core logic; build before UI)")
        else:
            ordering.append(f"- {line}")
    if not ordering:
        return "[analyze_task_dependencies] Empty task list."
    return "[analyze_task_dependencies]\n" + "\n".join(ordering)


def estimate_iteration_plan(task_count: int, team_size: int = 2) -> str:
    """
    Estimate iteration length given number of tasks and team members.

    Args:
        task_count: Total tasks from Project Manager output.
        team_size: Available engineers.

    Returns:
        Rough sprint plan summary.
    """
    if team_size <= 0:
        return "[estimate_iteration_plan] Invalid team size."
    days = max(1, round(task_count / max(1, team_size) * 1.5))
    weeks = max(1, round(days / 5))
    return (
        f"[estimate_iteration_plan] {task_count} tasks with {team_size} devs "
        f"≈ {weeks} week(s) ({days} workdays)."
    )


def infer_required_packages(design_text: str) -> str:
    """
    Infer likely dependencies (backend/frontend) from design keywords.

    Args:
        design_text: System design paragraph or bullet list.

    Returns:
        Package suggestions grouped by layer.
    """
    text = design_text.lower()
    packages = []
    if "database" in text or "sql" in text:
        packages.append("- backend: sqlmodel / psycopg2")
    if "api" in text or "rest" in text:
        packages.append("- backend: fastapi / flask")
    if "ui" in text or "dashboard" in text:
        packages.append("- frontend: react / vite / antd")
    if "ml" in text or "prediction" in text:
        packages.append("- analytics: scikit-learn / pandas")
    if not packages:
        packages.append("- general: requests / httpx")
    return "[infer_required_packages]\n" + "\n".join(packages)


# ---------------------------------------------------------------------------
# Default tool bundles for agents
# ---------------------------------------------------------------------------

ENGINEER_DEFAULT_TOOLS = [
    read_project_file,
    write_project_file,
    list_project_files,
    search_in_project_file,
    check_project_path,
    run_project_command,
    summarize_python_file,
]

CODE_REVIEW_DEFAULT_TOOLS = [
    read_project_file,
    search_in_project_file,
    check_project_path,
    run_python_linter,
    summarize_python_file,
]

PRODUCT_MANAGER_DEFAULT_TOOLS = [
    extract_requirement_keywords,
    draft_competitor_brief,
    summarize_user_personas,
]

ARCHITECT_DEFAULT_TOOLS = [
    read_project_file,
    list_project_files,
    propose_file_breakdown,
    recommend_architecture_pattern,
    validate_mermaid_snippet,
]

PROJECT_MANAGER_DEFAULT_TOOLS = [
    analyze_task_dependencies,
    estimate_iteration_plan,
    infer_required_packages,
]


__all__ = [
    # individual tools
    "read_project_file",
    "write_project_file",
    "list_project_files",
    "search_in_project_file",
    "check_project_path",
    "run_project_command",
    "summarize_python_file",
    "run_python_linter",
    "extract_requirement_keywords",
    "draft_competitor_brief",
    "summarize_user_personas",
    "propose_file_breakdown",
    "recommend_architecture_pattern",
    "validate_mermaid_snippet",
    "analyze_task_dependencies",
    "estimate_iteration_plan",
    "infer_required_packages",
    # bundles
    "ENGINEER_DEFAULT_TOOLS",
    "CODE_REVIEW_DEFAULT_TOOLS",
    "PRODUCT_MANAGER_DEFAULT_TOOLS",
    "ARCHITECT_DEFAULT_TOOLS",
    "PROJECT_MANAGER_DEFAULT_TOOLS",
]
