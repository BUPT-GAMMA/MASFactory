"""Filesystem-backed prompt templates with deterministic fallback text."""
from __future__ import annotations
from pathlib import Path

DEFAULTS = {
    "Generate": "Solve the problem and provide the final answer.",
    "GenerateCoT": "Solve the problem step by step, then provide the final answer.",
    "SelfRefine": "Improve the proposed solution and provide a corrected final answer.",
    "MultiGenerateCoT": "Produce an independent step-by-step solution.",
    "ScEnsemble": "Select the most consistent candidate solution.",
    "BootstrapGenerate": "Use the executed code output to produce the final solution and answer.",
    "Programmer": (
        "Write only executable Python code for the requested math problem. "
        "Define a zero-argument function named solve and print(solve()) at the end. "
        "Do not return Markdown fences or explanations."
    ),
}

class PromptLoader:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def load(self, operator: str, dataset: str | None = None) -> str:
        candidates = []
        if dataset:
            candidates.append(self.root / dataset.lower() / f"{operator}.txt")
        candidates.append(self.root / "shared" / f"{operator}.txt")
        for path in candidates:
            if path.exists():
                return path.read_text(encoding="utf-8")
        return DEFAULTS.get(operator, "Solve the problem.")

__all__ = ["PromptLoader"]
