from __future__ import annotations

import json
import locale
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

_BASE_DIR = Path(__file__).resolve().parent
BUILD_INSTRUCTIONS_DIR = _BASE_DIR / "assets" / "build_instructions"
CHATCHAIN_CONFIG_PATH = _BASE_DIR / "assets" / "config" / "ChatChainConfig.json"

DEFAULT_CHATDEV_PROMPT = (
    "ChatDev is a software company powered by multiple intelligent agents, such as chief executive officer, "
    "chief human resources officer, chief product officer, chief technology officer, etc, with a multi-agent "
    "organizational structure and the mission of 'changing the digital world through programming'."
)


def load_build_instructions(phase_name: str) -> str:
    path = BUILD_INSTRUCTIONS_DIR / f"{phase_name}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"Missing build instructions file: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_chatdev_prompt() -> str:
    try:
        if not CHATCHAIN_CONFIG_PATH.is_file():
            return DEFAULT_CHATDEV_PROMPT
        data = json.loads(CHATCHAIN_CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            prompt = data.get("background_prompt") or data.get("chatdev_prompt")
            if isinstance(prompt, str) and prompt.strip():
                return prompt.strip()
    except Exception:
        return DEFAULT_CHATDEV_PROMPT
    return DEFAULT_CHATDEV_PROMPT


def _append_run_log(attributes: dict[str, object] | None, text: str) -> None:
    if not attributes:
        return
    log_path = attributes.get("log_filepath") or attributes.get("log_file") or attributes.get("log_path")
    if not log_path:
        return
    try:
        p = Path(str(log_path))
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")
    except Exception:
        return


def init_workdir_forward(_input_dict: dict, attributes: dict) -> dict:
    existing = attributes.get("work_dir") or attributes.get("directory")
    if isinstance(existing, str) and existing.strip():
        wd = Path(existing.strip())
    else:
        base_dir = attributes.get("warehouse_base_dir")
        base = (
            Path(str(base_dir).strip())
            if isinstance(base_dir, str) and base_dir.strip()
            else _BASE_DIR / "assets" / "output" / "WareHouse"
        )

        start_time = str(attributes.get("start_time") or "").strip()
        if not start_time:
            start_time = time.strftime("%Y%m%d%H%M%S", time.localtime())
            attributes["start_time"] = start_time

        project = str(attributes.get("project_name") or attributes.get("name") or "chatdev_lite_vibegraph").strip()
        org = str(attributes.get("org_name") or attributes.get("org") or "DefaultOrganization").strip()
        project = re.sub(r"[^a-zA-Z0-9_.-]+", "_", project).strip("_.-") or "chatdev_lite_vibegraph"
        org = re.sub(r"[^a-zA-Z0-9_.-]+", "_", org).strip("_.-") or "DefaultOrganization"
        wd = base / f"{project}_{org}_{start_time}"

    wd.mkdir(parents=True, exist_ok=True)

    log_fp_raw = attributes.get("log_filepath")
    if isinstance(log_fp_raw, str) and log_fp_raw.strip():
        p = Path(log_fp_raw.strip())
        log_fp = (wd / p) if not p.is_absolute() else p
    else:
        log_fp = wd / "workflow.log"

    init_text = "\n".join(
        [
            "\n" + "=" * 80,
            "[chatdev_lite_vibegraph] Workdir initialized",
            f"- work_dir: {wd}",
            f"- log_filepath: {log_fp}",
        ]
    )
    _append_run_log({"log_filepath": str(log_fp)}, init_text)
    return {"work_dir": str(wd), "directory": str(wd), "log_filepath": str(log_fp)}


def test_terminate_condition(_input: dict, attributes: dict) -> bool:
    return not bool(attributes.get("exist_bugs_flag", True))


_META_FIELD_LINE_RE = re.compile(
    r"(?mi)^\s*(?:task|language|codes|test_reports|error_summary|chatdev_prompt|exist_bugs_flag)\s*:\s*"
)


def _strip_leading_codes_field_marker(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n")
    m = re.search(r"<content>\s*(.*?)\s*</content>", raw, re.DOTALL | re.IGNORECASE)
    if m:
        raw = m.group(1)

    lines = raw.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip().lower() in ("[codes]", "codes", "codes:"):
        lines.pop(0)
    return "\n".join(lines).strip()


def _looks_like_filename_line(text: str) -> bool:
    t = str(text or "").strip().strip("`").strip().strip('"').strip("'").rstrip(":")
    if not t or t.startswith("```") or " " in t:
        return False
    name = Path(t.replace("\\", "/")).name
    if "." not in name:
        return False
    if len(name) > 128:
        return False
    return True


def _extract_filename_candidate(line: str) -> str | None:
    t = str(line or "").strip().strip("`").strip().strip('"').strip("'")
    t = re.sub(r"^#+\s*", "", t)
    t = re.sub(r"^[*-]\s*", "", t)
    t = re.sub(r"^\d+[.)]\s*", "", t)
    t = t.rstrip(":").strip()
    return t if _looks_like_filename_line(t) else None


def _default_filename_for_block(index: int, language: str) -> str:
    lang = (language or "").strip().lower()
    ext = "py" if ("python" in lang or lang == "py") else "txt"
    return f"file_{index}.{ext}"


def _parse_codes_from_text(raw: str) -> list[dict[str, str]]:
    text = _strip_leading_codes_field_marker(raw)
    if not text:
        return []

    lines = text.replace("\r\n", "\n").splitlines()
    entries: list[dict[str, str]] = []
    i = 0
    block_index = 0

    while i < len(lines):
        filename = _extract_filename_candidate(lines[i])
        if filename is None:
            i += 1
            continue

        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines) or not lines[j].lstrip().startswith("```"):
            i += 1
            continue

        block_index += 1
        fence = lines[j].strip()
        language = fence[3:].strip()

        code_lines: list[str] = []
        k = j + 1
        while k < len(lines) and not lines[k].lstrip().startswith("```"):
            code_lines.append(lines[k])
            k += 1
        if k < len(lines) and lines[k].lstrip().startswith("```"):
            k += 1

        entries.append(
            {
                "filename": filename,
                "language": language,
                "code": "\n".join(code_lines).rstrip("\n"),
            }
        )
        i = k

    return entries


def _normalize_codes(codes: Any) -> list[dict[str, str]]:
    if codes is None:
        return []

    if isinstance(codes, list):
        normalized: list[dict[str, str]] = []
        for item in codes:
            if isinstance(item, dict):
                filename = str(item.get("filename") or item.get("file") or item.get("path") or "").strip()
                code = str(item.get("code") or item.get("content") or "").rstrip("\n")
                language = str(item.get("language") or "").strip()
                if filename and code:
                    normalized.append({"filename": filename, "language": language, "code": code})
            elif isinstance(item, str) and item.strip():
                normalized.extend(_parse_codes_from_text(item))
        return normalized

    if isinstance(codes, dict):
        if "code" in codes and ("filename" in codes or "file" in codes or "path" in codes):
            filename = str(codes.get("filename") or codes.get("file") or codes.get("path") or "").strip()
            code = str(codes.get("code") or "").rstrip("\n")
            language = str(codes.get("language") or "").strip()
            return [{"filename": filename, "language": language, "code": code}] if filename and code else []

        out: list[dict[str, str]] = []
        for k, v in codes.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                out.append({"filename": k, "language": "", "code": v.rstrip("\n")})
        return out

    if isinstance(codes, str):
        return _parse_codes_from_text(codes)

    return []


_WINDOWS_ILLEGAL_CHARS_RE = re.compile(r'[<>:"|?*]')


def _sanitize_path_component(component: str) -> str:
    c = str(component or "").strip().strip("`").strip().strip('"').strip("'")
    c = _WINDOWS_ILLEGAL_CHARS_RE.sub("_", c)
    c = re.sub(r"[^A-Za-z0-9._-]+", "_", c)
    c = re.sub(r"_+", "_", c).strip().strip("._-")
    return c


def _safe_relpath(filename: str, *, default_name: str) -> Path:
    raw = str(filename or "").strip().strip("`").strip().replace("\\", "/")
    raw = re.sub(r"^[A-Za-z]:", "", raw)  # drop drive letters
    raw = raw.lstrip("/")

    parts: list[str] = []
    for part in raw.split("/"):
        part = part.strip()
        if part in ("", ".", ".."):
            continue
        sanitized = _sanitize_path_component(part)
        if sanitized and sanitized not in (".", ".."):
            parts.append(sanitized)
    return Path(*parts) if parts else Path(default_name)


_META_TRIM_CODE_EXTS: set[str] = {
    "py",
    "js",
    "ts",
    "jsx",
    "tsx",
    "java",
    "c",
    "cc",
    "cpp",
    "cxx",
    "h",
    "hpp",
    "go",
    "rs",
    "cs",
    "php",
    "rb",
    "swift",
    "kt",
    "m",
    "mm",
    "sh",
    "ps1",
    "html",
    "css",
    "json",
    "yaml",
    "yml",
    "toml",
    "md",
}


def _clean_code_text(code: str, *, filename: str) -> str:
    text = str(code or "").replace("\r\n", "\n").strip("\n")
    if not text:
        return ""

    lines = text.split("\n")

    def _is_wrapper_line(line: str) -> bool:
        t = line.strip()
        return bool(t) and (t.startswith("```") or t in ("---", '"""', "'''", '"', "'", '""'))

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and _is_wrapper_line(lines[0]):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)

    ext = Path(filename).suffix.lstrip(".").lower()
    if ext in _META_TRIM_CODE_EXTS:
        for idx, line in enumerate(lines):
            if _META_FIELD_LINE_RE.match(line):
                lines = lines[:idx]
                break

    while lines and not lines[-1].strip():
        lines.pop()
    while lines and _is_wrapper_line(lines[-1]):
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()

    return "\n".join(lines).rstrip("\n")


def codes_check_and_processing_tool(
    codes: Any,
    *,
    attributes: dict[str, object],
    phase_info: str = "codes_check_and_processing",
    save_codes_alias: bool = False,
    update_existing_only: bool = False,
) -> str:
    directory = attributes.get("work_dir") or attributes.get("directory")
    if not directory or not str(directory).strip():
        status = "Error: directory missing"
        _append_run_log(attributes, f"[{phase_info}] {status}")
        return status

    entries = _normalize_codes(codes)
    if not entries:
        status = "Error: codes list is empty"
        _append_run_log(attributes, f"[{phase_info}] {status}")
        return status

    wd = Path(str(directory).strip())
    wd.mkdir(parents=True, exist_ok=True)

    language_hint = str(attributes.get("language") or "").strip().lower()
    if not update_existing_only and "python" in language_hint:
        entry_names = {"main.py", "app.py", "run.py"}

        def pythonish_score(code_text: str) -> int:
            low = (code_text or "").lower()
            score = 0
            if "if __name__" in low:
                score += 3
            if re.search(r"(?m)^\s*def\s+main\s*\(", code_text or ""):
                score += 2
            if re.search(r"(?m)^\s*import\s+\w+", code_text or ""):
                score += 1
            return score

        for e in entries:
            base = Path(str(e.get("filename") or "")).name.lower()
            if base in entry_names:
                e["filename"] = base
                break
        else:
            best = max(entries, key=lambda e: (pythonish_score(str(e.get("code") or "")), len(str(e.get("code") or ""))))
            best["filename"] = "main.py"

    allowed_map: dict[str, Path] = {}
    if update_existing_only:
        raw_allowed = attributes.get("coding_code_files") or attributes.get("saved_code_files")
        allowed: set[Path] = set()
        if isinstance(raw_allowed, list):
            for p in raw_allowed:
                if isinstance(p, str) and p.strip():
                    allowed.add(Path(p))
        if not allowed:
            try:
                allowed = {p.relative_to(wd) for p in wd.rglob("*") if p.is_file()}
            except Exception:
                allowed = set()
        allowed_map = {str(p).replace("\\", "/").lower(): p for p in allowed}

    written: list[str] = []
    skipped_new: list[str] = []
    for idx, entry in enumerate(entries, start=1):
        filename = str(entry.get("filename") or "").strip()
        code = _strip_leading_codes_field_marker(str(entry.get("code") or ""))
        if not filename or not code.strip():
            continue

        rel = _safe_relpath(filename, default_name=_default_filename_for_block(idx, str(entry.get("language") or "")))
        rel_norm = str(rel).replace("\\", "/").lower()
        out_path = wd / rel

        if update_existing_only:
            if allowed_map:
                existing_rel = allowed_map.get(rel_norm)
                if not existing_rel:
                    skipped_new.append(str(rel))
                    continue
                rel = existing_rel
                out_path = wd / rel
            else:
                if not out_path.is_file():
                    skipped_new.append(str(rel))
                    continue

        cleaned = _clean_code_text(code, filename=str(rel))
        if not cleaned.strip():
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(cleaned + ("\n" if not cleaned.endswith("\n") else ""), encoding="utf-8")
        written.append(str(rel).replace("\\", "/"))

    if not written:
        if update_existing_only and skipped_new:
            status = (
                "Error: No valid code updates applied (update_existing_only=True). "
                f"Skipped {len(skipped_new)} new file(s)."
            )
        else:
            status = "Error: No valid codes found after normalization"
        _append_run_log(attributes, f"[{phase_info}] {status}")
        return status

    if save_codes_alias:
        attributes["codes_alias"] = codes
    attributes["saved_code_files"] = written
    if phase_info.strip().lower().startswith("coding"):
        attributes["coding_code_files"] = list(written)

    codes_list: list[dict[str, str]] = []
    code_files_raw = attributes.get("coding_code_files")
    code_files = code_files_raw if isinstance(code_files_raw, list) and code_files_raw else written
    for rel_str in code_files:
        if not isinstance(rel_str, str) or not rel_str.strip():
            continue
        rel = Path(rel_str)
        fp = wd / rel
        if not fp.is_file():
            continue
        try:
            code_content = fp.read_text(encoding="utf-8", errors="ignore").rstrip("\n")
        except Exception:
            continue

        filename = str(rel).replace("\\", "/")
        ext = fp.suffix.lstrip(".").lower()
        language = "python" if ext == "py" else (ext or "")
        docstring = ""
        if language == "python":
            m = re.search(r'^\s*["\']{3}(.*?)["\']{3}', code_content, re.DOTALL | re.MULTILINE)
            if m:
                docstring = m.group(1).strip()
        codes_list.append({"filename": filename, "language": language, "docstring": docstring, "code": code_content})
    if codes_list:
        attributes["codes"] = codes_list

    status = f"Saved {len(written)} file(s) to {wd} ({phase_info})"
    if skipped_new:
        status += f"; skipped {len(skipped_new)} new file(s)"
    _append_run_log(attributes, f"[{phase_info}] {status}")
    return status


def _make_codes_check_and_processing_forward(
    *,
    phase_info: str = "codes_check_and_processing",
    save_codes_alias: bool = False,
    update_existing_only: bool = False,
    skip_when_no_bugs: bool = False,
) -> Callable[[dict, dict], dict]:
    def _forward(messages: dict, attributes: dict) -> dict:
        if skip_when_no_bugs and not bool(attributes.get("exist_bugs_flag", True)):
            _append_run_log(attributes, f"[{phase_info}] skip code saving (exist_bugs_flag=False)")
            return messages

        codes_check_and_processing_tool(
            attributes.get("codes"),
            attributes=attributes,
            phase_info=phase_info,
            save_codes_alias=save_codes_alias,
            update_existing_only=update_existing_only,
        )
        return messages

    return _forward


_MISSING_MODULE_RE = re.compile(r"No module named ['\"](?P<module>[^'\"]+)['\"]")


def _coerce_subprocess_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            encoding = locale.getpreferredencoding(False) or "utf-8"
            return bytes(value).decode(encoding, errors="replace")
        except Exception:
            return str(value)
    return str(value)


def _select_entry_script(directory: Path) -> str | None:
    for name in ("main.py", "app.py", "run.py"):
        if (directory / name).is_file():
            return name
    return None


def _run_entry_once(*, directory: Path, entry: str, timeout_s: float = 3.0) -> tuple[bool, str]:
    cmd = [sys.executable or "python", entry]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(directory),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
        stdout = _coerce_subprocess_text(completed.stdout)
        stderr = _coerce_subprocess_text(completed.stderr)
        combined = (stdout + "\n" + stderr).strip("\n")
        if completed.returncode == 0:
            return False, combined or "The software run successfully without errors."
        return True, combined or f"Process exited with code {completed.returncode}."
    except subprocess.TimeoutExpired as te:
        stdout = _coerce_subprocess_text(getattr(te, "stdout", None) or getattr(te, "output", None))
        stderr = _coerce_subprocess_text(getattr(te, "stderr", None))
        combined = (stdout + "\n" + stderr).strip("\n")
        if "Traceback" in combined or "ModuleNotFoundError" in combined or "Error" in combined:
            return True, combined or f"Timed out after {timeout_s:.1f}s."
        return False, combined or f"Process is still running after {timeout_s:.1f}s (treated as success)."
    except Exception as e:
        return True, f"Error running {' '.join(cmd)} in {directory}: {e}"


def _install_missing_modules(modules: list[str]) -> list[str]:
    logs: list[str] = []
    unique: list[str] = []
    for m in modules:
        m = m.strip()
        if m and m not in unique:
            unique.append(m)
    if not unique:
        return logs

    uv = shutil.which("uv")
    for module in unique[:8]:
        cmd = [uv, "pip", "install", module] if uv else [sys.executable or "python", "-m", "pip", "install", module]
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=False)
            logs.append(f"$ {' '.join(cmd)}")
            if completed.stdout:
                logs.append(completed.stdout.strip())
            if completed.stderr:
                logs.append(completed.stderr.strip())
            logs.append(f"(exit_code={completed.returncode})")
        except Exception as e:
            logs.append(f"$ {' '.join(cmd)}")
            logs.append(f"(install failed: {e})")
    return logs


def run_tests_tool(messages: dict, attributes: dict) -> dict:
    directory_raw = attributes.get("work_dir") or attributes.get("directory")
    if not directory_raw or not str(directory_raw).strip():
        report = "Error: directory missing"
        _append_run_log(attributes, f"[run_tests_tool] {report}")
        return {**messages, "test_reports": report, "exist_bugs_flag": True}

    directory = Path(str(directory_raw).strip())
    if not directory.exists():
        report = f"Error: directory not found: {directory}"
        _append_run_log(attributes, f"[run_tests_tool] {report}")
        return {**messages, "test_reports": report, "exist_bugs_flag": True}

    language = str(attributes.get("language") or "").strip().lower()
    entry = _select_entry_script(directory)
    if not entry:
        if "python" not in language:
            report = (
                "[run_tests_tool] skipped: non-Python project or no Python entry script found.\n"
                f"- language: {attributes.get('language')}\n"
                f"- directory: {directory}\n"
                "- expected (Python): main.py/app.py/run.py"
            )
            _append_run_log(attributes, report)
            try:
                (directory / "test_reports.txt").write_text(report + "\n", encoding="utf-8")
            except Exception:
                pass
            return {**messages, "test_reports": report, "exist_bugs_flag": False}

        report = f"Error: entry script not found in {directory} (expected main.py/app.py/run.py)"
        _append_run_log(attributes, f"[run_tests_tool] {report}")
        try:
            (directory / "test_reports.txt").write_text(report + "\n", encoding="utf-8")
        except Exception:
            pass
        return {**messages, "test_reports": report, "exist_bugs_flag": True}

    report_lines: list[str] = [
        "[run_tests_tool] execute entry script",
        f"- directory: {directory}",
        f"- entry: {entry}",
        f"- python: {sys.executable or 'python'}",
        "",
    ]

    exist_bugs, test_reports = _run_entry_once(directory=directory, entry=entry, timeout_s=3.0)
    report_lines.append("[run_tests_tool] first run")
    report_lines.append(test_reports)

    missing = [m.group("module") for m in _MISSING_MODULE_RE.finditer(test_reports)]
    if missing:
        report_lines.append("")
        report_lines.append("[run_tests_tool] detected ModuleNotFoundError, installing dependencies")
        report_lines.extend(_install_missing_modules(missing))

        exist_bugs, test_reports2 = _run_entry_once(directory=directory, entry=entry, timeout_s=3.0)
        report_lines.append("")
        report_lines.append("[run_tests_tool] second run (after dependency install)")
        report_lines.append(test_reports2)

    merged_report = "\n".join(report_lines).strip()
    try:
        (directory / "test_reports.txt").write_text(merged_report + "\n", encoding="utf-8")
    except Exception:
        pass

    _append_run_log(attributes, f"[run_tests_tool] exist_bugs_flag={exist_bugs}")
    return {**messages, "test_reports": merged_report, "exist_bugs_flag": bool(exist_bugs)}


def generate_meta(
    keys: list[str],
    meta_filename: str = "meta.txt",
) -> Callable[[dict, dict], dict]:
    """Generate a meta.txt file with specified attributes.
    
    Args:
        keys: List of attribute keys to include in the meta file
        meta_filename: Name of the output meta file (default: "meta.txt")
    
    Returns:
        A forward function that generates the meta file
    """
    def _forward(messages: dict, attributes: dict) -> dict:
        directory = attributes.get("work_dir") or attributes.get("directory")
        if not directory or not str(directory).strip():
            _append_run_log(attributes, f"[generate_meta] Error: directory missing")
            return messages
        
        directory_path = Path(str(directory).strip())
        directory_path.mkdir(parents=True, exist_ok=True)
        
        # Collect values for specified keys
        meta_content_lines = []
        for key in keys:
            value = attributes.get(key)
            if value is not None:
                meta_content_lines.append(f"{key}: {value}")
        
        # Write meta file
        meta_file_path = directory_path / meta_filename
        try:
            meta_file_path.write_text("\n".join(meta_content_lines) + "\n", encoding="utf-8")
            _append_run_log(attributes, f"[generate_meta] Generated {meta_filename} with {len(keys)} keys")
        except Exception as e:
            _append_run_log(attributes, f"[generate_meta] Error writing {meta_filename}: {e}")
        
        return messages
    
    return _forward
