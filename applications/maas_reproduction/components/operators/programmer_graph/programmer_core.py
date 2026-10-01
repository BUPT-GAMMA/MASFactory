"""Shared Programmer primitives used by dynamic and bootstrap entry points."""
from __future__ import annotations

import ast
from typing import Any

from .workflow_helpers import call_adapter, extract_code


class ProgrammerCore:
    """Single implementation of code generation, parsing, execution and retry."""

    def __init__(self, *, generator: Any, executor: Any, max_attempts: int = 3) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        self.generator = generator
        self.executor = executor
        self.max_attempts = max_attempts

    @staticmethod
    def parse(value: Any) -> str:
        code = extract_code(value)
        if not isinstance(code, str) or not code.strip():
            raise ValueError("programmer did not return code")
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise ValueError(f"generated code is invalid Python: {exc.msg} at line {exc.lineno}") from exc
        solve_functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "solve"
        ]
        if not solve_functions:
            raise ValueError("generated code has no solve function")
        if not any(
            not node.args.posonlyargs
            and not node.args.args
            and not node.args.kwonlyargs
            and node.args.vararg is None
            and node.args.kwarg is None
            for node in solve_functions
        ):
            raise ValueError("generated solve function must accept zero arguments")
        return code

    @staticmethod
    def _response_preview(value: Any, *, limit: int = 2000) -> str:
        if isinstance(value, dict):
            raw = value.get("code") or value.get("solution") or value.get("response") or value
        else:
            raw = value
        return str(raw)[:limit]

    def execute(self, payload: dict[str, Any], code: str) -> tuple[bool, str, str]:
        if self.executor is None:
            raise RuntimeError("programmer executor is not configured")
        output = call_adapter(self.executor, {**payload, "code": code})
        if isinstance(output, dict) and output.get("success", True) is False:
            error = str(output.get("error", "execution failed"))
            return False, error, error
        text = output if isinstance(output, str) else str(output)
        return True, text, ""

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        feedback = str(payload.get("feedback", "") or "")
        last_code: str | None = None
        last_output = ""
        last_error = ""
        diagnostics: list[dict[str, Any]] = []
        for attempt in range(1, self.max_attempts + 1):
            generated = call_adapter(self.generator, {**payload, "feedback": feedback, "attempt": attempt})
            try:
                code = self.parse(generated)
            except ValueError as exc:
                last_error = f"Code format error: {exc}"
                diagnostics.append({
                    "attempt": attempt,
                    "stage": "parse",
                    "error": str(exc),
                    "raw_response_preview": self._response_preview(generated),
                    "extracted_code_block": "```" in self._response_preview(generated),
                })
                feedback = (
                    f"{last_error}\n"
                    "Return only executable Python source code. The program must contain a real "
                    "zero-argument function definition named solve and end with print(solve())."
                )
                continue
            last_code = code
            success, output, error = self.execute(payload, code)
            last_output, last_error = output, error
            if success:
                return {
                    "code": code,
                    "output": output,
                    "attempts": attempt,
                    "attempt_diagnostics": diagnostics,
                }
            diagnostics.append({
                "attempt": attempt,
                "stage": "execute",
                "error": error,
                "raw_response_preview": self._response_preview(generated),
                "extracted_code_block": "```" in self._response_preview(generated),
            })
            feedback = (
                "The previous program failed during execution:\n"
                f"{error}\n"
                "Correct the program and return the complete corrected Python source code."
            )
        return {
            "code": last_code,
            "output": last_output,
            "error": last_error or "programmer failed after all attempts",
            "attempts": self.max_attempts,
            "attempt_diagnostics": diagnostics,
        }


__all__ = ["ProgrammerCore"]
