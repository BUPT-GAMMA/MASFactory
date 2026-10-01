"""Safe public artifact persistence."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Mapping

class ArtifactStore:
    def __init__(self, root: str | Path, *, results_root: str | Path | None = None):
        self.root = Path(root)
        self.results_root = Path(results_root) if results_root is not None else self.root
        self.root.mkdir(parents=True, exist_ok=True)
        self.results_root.mkdir(parents=True, exist_ok=True)
    def _write(self, name: str, value: Mapping[str, Any]) -> Path:
        _reject_expected_answer(value)
        text = json.dumps(dict(value), ensure_ascii=False, indent=2, default=str)
        path = self.root / name; path.write_text(text, encoding="utf-8"); return path
    def write_config(self, value: Mapping[str, Any]) -> Path: return self._write("config.json", value)
    def write_sample_result(self, value: Mapping[str, Any]) -> Path:
        _reject_expected_answer(value)
        text = json.dumps(dict(value), ensure_ascii=False, indent=2, default=str)
        path = self.results_root / f"sample_{value.get('problem_index', 0)}.json"
        path.write_text(text, encoding="utf-8")
        return path
    def write_metrics(self, value: Mapping[str, Any]) -> Path: return self._write("metrics.json", value)


def _reject_expected_answer(value: Any) -> None:
    """Reject private evaluator/model fields recursively, by exact key."""
    private_keys = {
        "expected_answer", "prompt", "api_key", "openai_api_key",
        "model_client", "dispatch_state", "route_state",
    }
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in private_keys:
                raise ValueError(f"forbidden private data in artifact: {key}")
            _reject_expected_answer(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_expected_answer(child)

__all__ = ["ArtifactStore"]
