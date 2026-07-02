from __future__ import annotations

from pathlib import Path
from typing import Any

from masfactory.aml import graph_design_to_aml_document

from .compiler import load_cached_aml, normalize_graph_design
from .vibe_graph import VibeGraph


def _legacy_aml_cache_sibling(path: str | Path) -> Path:
    cache_path = Path(path)
    if cache_path.suffix.lower() == ".aml":
        return cache_path
    if cache_path.name.endswith(".graph_design.json"):
        return cache_path.with_name(cache_path.name[: -len(".graph_design.json")] + ".aml")
    return cache_path.with_suffix(".aml")


def _legacy_resolve_build_cache_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    cache_path = Path(path)
    if cache_path.suffix.lower() == ".aml" or cache_path.exists():
        return cache_path
    aml_path = _legacy_aml_cache_sibling(cache_path)
    if aml_path.exists():
        return aml_path
    return aml_path


def _legacy_aml_from_workflow_output(
    output: dict[str, Any],
    *,
    document_id: str,
    root_graph_id: str,
) -> str:
    raw_aml = output.get("aml")
    if isinstance(raw_aml, str) and raw_aml.strip():
        return raw_aml

    raw_graph_design = output.get("graph_design", {})
    if isinstance(raw_graph_design, str) and raw_graph_design.lstrip().startswith("<aml"):
        return raw_graph_design

    graph_design = normalize_graph_design(raw_graph_design)
    return graph_design_to_aml_document(
        graph_design,
        document_id=document_id,
        root_graph_id=root_graph_id,
        source="legacy_vibe_graph_design_output",
    )


class LegacyVibeGraph(VibeGraph):
    """Legacy VibeGraph wrapper for graph_design workflows and caches.

    New workflows should use ``VibeGraph`` and emit AML directly. This class is
    retained as an explicit migration path for older build prompts and caches
    that still produce or store ``graph_design`` JSON.
    """

    def _resolve_cache_path(self) -> Path | None:
        return _legacy_resolve_build_cache_path(self._build_cache_path)

    def _coerce_workflow_output(self, output: dict[str, Any]) -> str:
        return _legacy_aml_from_workflow_output(
            output,
            document_id=f"{self.name}.vibe_cache",
            root_graph_id=self.name,
        )

    def _load_cached_design(self, cache_path: Path) -> str | Path:
        return load_cached_aml(cache_path)


__all__ = ["LegacyVibeGraph"]
