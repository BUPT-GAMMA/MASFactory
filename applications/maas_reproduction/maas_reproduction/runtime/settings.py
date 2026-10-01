"""Validated, side-effect-free runtime configuration."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path

@dataclass(frozen=True)
class ModelSettings:
    provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    base_url_env: str | None = "BASE_URL"
    temperature: float = 0.0
    max_tokens: int = 2048
    # Monetary rates are deliberately explicit.  A gateway may expose token
    # usage without exposing its price; in that case cost is unreliable and
    # policy training must be skipped rather than fabricated.
    input_cost_per_1k_tokens: float | None = None
    output_cost_per_1k_tokens: float | None = None

@dataclass(frozen=True)
class RuntimeSettings:
    dataset: str = "GSM8K"
    split: str = "test"
    mode: str = "test"
    round_number: int = 1
    sample: int = 1
    batch_size: int = 1
    epochs: int = 1
    seed: int = 42
    learning_rate: float = 1e-3
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    output_root: Path = Path("assets/output")
    model: ModelSettings = ModelSettings()

def load_settings(config_root: str | Path, *, mode_override: str | None = None,
                  dataset_override: str | None = None, split_override: str | None = None,
                  sample_override: int | None = None,
                  epochs_override: int | None = None) -> RuntimeSettings:
    root = Path(config_root)
    def read(name: str) -> dict:
        path = root / name
        if not path.exists() or not path.read_text(encoding="utf-8").strip(): return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict): raise ValueError(f"{name} must contain a JSON object")
        return value
    model_data, experiment = read("models.json"), read("experiments.json")
    model = ModelSettings(**{k: model_data[k] for k in ModelSettings.__dataclass_fields__ if k in model_data})
    dataset, split, mode = dataset_override or experiment.get("dataset", "GSM8K"), split_override or experiment.get("split", "test"), mode_override or experiment.get("mode", "test")
    if dataset not in {"GSM8K", "MATH", "HumanEval"}: raise ValueError("unsupported dataset")
    if split not in {"train", "test"}: raise ValueError("split must be train or test")
    if mode not in {"train", "test", "smoke"}: raise ValueError("unsupported mode")
    def positive(name: str, default: int) -> int:
        value = experiment.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0: raise ValueError(f"{name} must be positive")
        return value
    def override(name: str, value: int | None, default: int) -> int:
        resolved = value if value is not None else positive(name, default)
        if isinstance(resolved, bool) or not isinstance(resolved, int) or resolved <= 0:
            raise ValueError(f"{name} must be positive")
        return resolved
    sample = override("sample", sample_override, 1)
    epochs = override("epochs", epochs_override, 1)
    return RuntimeSettings(dataset, split, mode, positive("round_number", 1), sample, positive("batch_size", 1), epochs, int(experiment.get("seed", 42)), float(experiment.get("learning_rate", 1e-3)), str(experiment.get("embedding_model", RuntimeSettings.embedding_model)), Path(experiment.get("output_root", "assets/output")), model)

__all__ = ["ModelSettings", "RuntimeSettings", "load_settings"]
