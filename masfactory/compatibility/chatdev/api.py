from __future__ import annotations

from pathlib import Path
from typing import Any

from masfactory.compatibility.chatdev.parse import chatdev_document_to_blueprint
from masfactory.compatibility.common.aml_export import (
    blueprint_to_aml_document,
    blueprint_to_graph_design_document_via_aml,
    blueprint_to_graph_via_aml,
)
from masfactory.compatibility.common.loaders import load_mapping_source
from masfactory.compatibility.common.llm_options import ChatDevCompileOptions
from masfactory.compatibility.paths import maybe_export_aml, maybe_export_graph_design
from masfactory.components.graphs.graph import Graph


def load_graph_from_chatdev_yaml(
    source: str | Path | bytes,
    *,
    graph_name: str = "chatdev_import",
    options: ChatDevCompileOptions | None = None,
    use_placeholder: bool = False,
    graph_design_path: str | Path | bool | None = None,
    aml_path: str | Path | bool | None = None,
) -> Graph:
    """Load ChatDev YAML through AML into a MASFactory graph.

    ``use_placeholder`` is retained for API compatibility; the load path no
    longer bypasses AML.
    """
    _ = use_placeholder
    doc, input_path = load_mapping_source(source, label="ChatDev document")
    bp = chatdev_document_to_blueprint(doc, base_path=input_path)
    fmt = (bp.metadata or {}).get("chatdev", {}).get("format", "workflow")
    maybe_export_graph_design(
        bp,
        graph_design_path,
        source=f"chatdev_{fmt}",
        input_path=input_path,
    )
    maybe_export_aml(
        bp,
        aml_path,
        source=f"chatdev_{fmt}",
        input_path=input_path,
    )
    model = None
    if options is not None and (
        options.model_factory is not None
        or options.use_stub_llm
        or options.openai_api_key
        or options.openai_base_url
    ):
        model = options.resolve_model({"name": graph_name, "source": f"chatdev_{fmt}"})
    return blueprint_to_graph_via_aml(bp, graph_name=graph_name, source=f"chatdev_{fmt}", model=model)


def chatdev_document_to_graph_design(
    doc: dict[str, Any],
    *,
    base_path: Path | str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Return a deprecated ``{graph_design: ...}`` document through the AML path."""
    bp = chatdev_document_to_blueprint(doc, base_path=base_path)
    fmt = (bp.metadata or {}).get("chatdev", {}).get("format", "workflow")
    return blueprint_to_graph_design_document_via_aml(bp, source=source or f"chatdev_{fmt}")


def chatdev_document_to_aml(
    doc: dict[str, Any],
    *,
    base_path: Path | str | None = None,
    source: str | None = None,
) -> str:
    """Return a Visualizer-previewable AML document from ChatDev export."""
    bp = chatdev_document_to_blueprint(doc, base_path=base_path)
    fmt = (bp.metadata or {}).get("chatdev", {}).get("format", "workflow")
    return blueprint_to_aml_document(bp, source=source or f"chatdev_{fmt}")
