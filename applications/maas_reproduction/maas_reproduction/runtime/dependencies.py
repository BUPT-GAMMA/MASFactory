"""Named runtime dependency bundle used by bootstrap and runners."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

@dataclass
class RuntimeDependencies:
    settings: Any
    model: Any
    embedding_provider: Any
    policy_controller: Any
    operator_embeddings: Any
    operator_catalog: tuple[str, ...]
    operator_registry: Mapping[str, Mapping[str, Any]]
    scorer: Any
    cost_tracker: Any
    checkpoint_manager: Any
    optimizer: Any = None
    batch_accumulator: Any = None
    root_graph: Any = None
    dataset_runner: Any = None
    artifact_store: Any = None

__all__ = ["RuntimeDependencies"]
