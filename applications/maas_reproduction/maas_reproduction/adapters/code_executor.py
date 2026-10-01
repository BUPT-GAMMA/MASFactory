"""Restricted subprocess code execution adapter."""
from __future__ import annotations
from dataclasses import dataclass
import subprocess, sys, tempfile, os

@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    error: str | None = None

class CodeExecutor:
    def __init__(self, *, max_output_chars: int = 10000): self.max_output_chars = max_output_chars
    def execute(self, code: str, *, timeout_seconds: float = 10.0) -> ExecutionResult:
        if not isinstance(code, str) or not code.strip(): return ExecutionResult(False,"","",None,False,"empty code")
        if timeout_seconds <= 0: raise ValueError("timeout_seconds must be positive")
        path = None
        try:
            fd, path = tempfile.mkstemp(suffix=".py"); os.close(fd)
            with open(path, "w", encoding="utf-8") as handle: handle.write(code)
            proc = subprocess.run([sys.executable, "-I", path], capture_output=True, text=True, timeout=timeout_seconds)
            out, err = proc.stdout[:self.max_output_chars], proc.stderr[:self.max_output_chars]
            return ExecutionResult(proc.returncode == 0, out, err, proc.returncode, False, None if proc.returncode == 0 else "nonzero exit")
        except subprocess.TimeoutExpired as exc:
            return ExecutionResult(False, str(exc.stdout or "")[:self.max_output_chars], str(exc.stderr or "")[:self.max_output_chars], None, True, "timeout")
        except Exception as exc:
            return ExecutionResult(False, "", "", None, False, f"{type(exc).__name__}: {exc}")
        finally:
            if path and os.path.exists(path): os.unlink(path)

__all__ = ["ExecutionResult", "CodeExecutor"]
