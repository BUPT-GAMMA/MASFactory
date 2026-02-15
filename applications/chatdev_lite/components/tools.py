"""ChatDev Lite Tools - Converted from post actions

All tools are designed as idempotent operations and can be safely called multiple times.
"""

from __future__ import annotations
import os, json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import re
@dataclass
class RuntimeContext:
    """Runtime context holding directory and manager references"""
    directory: str = None
    code_manager: Any = None
    requirement_manager: Any = None
    manual_manager: Any = None
    git_management: bool = False
    attributes: dict = None  # Reference to global attributes for dynamic updates

_RUNTIME: Optional[RuntimeContext] = None

def set_runtime(context: RuntimeContext) -> None:
    """Register runtime context. Call once before phases start."""
    global _RUNTIME
    _RUNTIME = context

def _require_runtime() -> RuntimeContext:
    """Get runtime context, auto-sync directory from attributes if needed"""
    if _RUNTIME is None:
        raise RuntimeError("RuntimeContext not set. Call set_runtime(...) before tool usage.")
    if _RUNTIME.attributes and not _RUNTIME.directory:
        _RUNTIME.directory = _RUNTIME.attributes.get('directory')
    return _RUNTIME

def check_code_completeness_tool() -> str:
    """
    Check if there are any unimplemented files (containing 'pass' or 'NotImplementedError').
    
    Returns:
        str: JSON string with structure {"filename": str or null}
    """
    try:
        rt = _require_runtime()
        if not rt.directory or not os.path.isdir(rt.directory):
            return json.dumps({"unimplemented_file": None}, ensure_ascii=False)

        for name in os.listdir(rt.directory):
            if not name.endswith(".py"): 
                continue
            p = os.path.join(rt.directory, name)
            try:
                txt = open(p, "r", encoding="utf-8").read()
            except Exception as e:
                continue
            if "pass" in txt or "NotImplementedError" in txt:
                return json.dumps({
                    "unimplemented_file": name
                }, ensure_ascii=False)
        return json.dumps({"unimplemented_file": None}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "unimplemented_file": None}, ensure_ascii=False)

def run_tests_tool(messages:dict, attributes: dict) -> str:
    """
    Run code tests and summarize errors.
    This tool analyzes the code by running the main entry script (main.py/app.py/run.py) and collects test results.
    If a ModuleNotFoundError is detected, it will attempt to fix the missing module and print installation suggestions.
    Args:
        messages (dict): Contextual messages for the test phase.
        attributes (dict): Runtime attributes, including test_reports and other state.
    Returns:
        dict: Updated messages with test results, error summary, and skip flag.
    """
    from applications.chatdev_lite.components.handlers import generate_images_from_codes, _exist_bugs, fix_module_not_found_error
    messages = generate_images_from_codes(messages, attributes)
    (exist_bugs, test_reports) = _exist_bugs(messages, attributes)
    if "ModuleNotFoundError" in test_reports:
        fix_module_not_found_error(test_reports)
        pip_install_content = ""
        for match in re.finditer(r"No module named '(\S+)'", attributes.get('test_reports', ''), re.DOTALL):
            module = match.group(1)
            pip_install_content += "{}\n```{}\n{}\n```\n".format("cmd", "bash", f"uv pip install {module}")
        messages["error_summary"] = "nothing need to do"
        messages["skip_flag"] = True
    else:
        messages["exist_bugs_flag"] = exist_bugs
        messages["test_reports"] = test_reports
        messages["skip_flag"] = False
    return messages

def save_requirements_tool(content: str) -> str:
    """
    Write requirements.txt.
    Args:
        content (str): Full file content.
    Returns:
        str: Status.
    """
    try:
        rt = _require_runtime()
        path = os.path.join(rt.directory, "requirements.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        if rt.requirement_manager:
            rt.requirement_manager._update_documents([{"filename": "requirements.txt", "content": content}])
        return "Saved requirements.txt."
    except Exception as e:
        return f"Error: {e}"

def save_manual_tool(content: str) -> str:
    """
    Write manual.md.
    Args:
        content (str): Markdown manual content.
    Returns:
        str: Status.
    """
    try:
        rt = _require_runtime()
        path = os.path.join(rt.directory, "manual.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        if rt.manual_manager:
            rt.manual_manager._update_documents([{"filename": "manual.md", "content": content}])
        return "Saved manual.md."
    except Exception as e:
        return f"Error: {e}"

def codes_check_and_processing_tool(
    codes: List[Dict[str, Any]],
    phase_info: str = "codes_check_and_processing",
    save_codes_alias: bool = False
) -> str:
    """
    Check and process code files: validate, update code manager, and rewrite to disk.
    This is the tool version of codes_check_and_processing post-action.
    
    Args:
        codes (list[dict]): List of code dictionaries with filename, code, docstring, language
        phase_info (str): Information about current phase for rewrite logging
        save_codes_alias (bool): Whether to save a copy of codes as codes_alias
    
    Returns:
        str: Status message with number of files processed
    """
    try:
        rt = _require_runtime()
        
        if not rt.code_manager:
            return "Error: code_manager missing"
        if not rt.directory:
            return "Error: directory missing"
        
        # Validate codes input
        if not codes or len(codes) == 0:
            return "Error: codes list is empty"
        
        # Update code manager with new codes
        rt.code_manager._update_codes(codes)
        
        # Check if any valid codes were added
        if len(rt.code_manager.codebooks.keys()) == 0:
            return "Error: No valid codes found after update"
        
        # Set directory and rewrite codes to disk
        rt.code_manager.directory = rt.directory
        rt.code_manager._rewrite_codes(rt.git_management, phase_info=phase_info)
        
        # Update attributes if available
        if rt.attributes:
            rt.attributes["code_manager"] = rt.code_manager
            if save_codes_alias:
                rt.attributes["codes_alias"] = codes
            rt.attributes["codes"] = rt.code_manager._get_codes()
        
        num_files = len(rt.code_manager.codebooks.keys())
        return f"Successfully processed and saved {num_files} code file(s) to {rt.directory}"
        
    except ValueError as ve:
        return f"Validation Error: {ve}"
    except Exception as e:
        import traceback
        return f"Error: {e}\n{traceback.format_exc()}"


__all__ = [
    "RuntimeContext",
    "set_runtime",
    "check_code_completeness_tool",
    "run_tests_tool",
    "save_requirements_tool",
    "save_manual_tool",
    "codes_check_and_processing_tool",
]
