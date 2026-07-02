from __future__ import annotations

from pathlib import Path

from masfactory.compatibility.common.aml_export import (
    blueprint_to_aml_document,
    blueprint_to_graph_design_document_via_aml,
    blueprint_to_graph_via_aml,
)
from masfactory.compatibility.common.loaders import load_mapping_source
from masfactory.compatibility.common.names import slugify_node_name
from masfactory.compatibility.common.workflow_parse import workflow_export_to_blueprint
from masfactory.compatibility.dify.options import DifyCompileOptions
from masfactory.compatibility.dify.parse import dify_document_to_blueprint, is_dify_app_document
from masfactory.compatibility.paths import maybe_export_aml, maybe_export_graph_design
from masfactory.components.graphs.graph import Graph


def _document_to_blueprint(doc: dict):
    if is_dify_app_document(doc):
        return dify_document_to_blueprint(doc), True
    return workflow_export_to_blueprint(doc), False


def _default_graph_name(metadata: dict | None) -> str:
    if metadata:
        dify_meta = metadata.get("dify") or {}
        app_name = dify_meta.get("app_name")
        if isinstance(app_name, str) and app_name.strip():
            return slugify_node_name(app_name, fallback="dify_import")
    return "dify_import"


def _compile_dify_blueprint(
    bp,
    is_app: bool,
    *,
    graph_name: str | None,
    options: DifyCompileOptions | None,
) -> Graph:
    name = graph_name or _default_graph_name(bp.metadata)
    source = "dify_app" if is_app else "dify_generic"
    model = None
    if options is not None and (
        options.model_factory is not None
        or options.use_stub_llm
        or options.openai_api_key
        or options.openai_base_url
    ):
        model = options.resolve_model({"name": name, "source": source})
    return blueprint_to_graph_via_aml(bp, graph_name=name, source=source, model=model)


def _load_graph_from_dify(
    doc: dict,
    *,
    input_path: Path | None,
    graph_name: str | None,
    options: DifyCompileOptions | None,
    graph_design_path: str | Path | bool | None,
    aml_path: str | Path | bool | None,
) -> Graph:
    bp, is_app = _document_to_blueprint(doc)
    maybe_export_graph_design(bp, graph_design_path, source="dify", input_path=input_path)
    maybe_export_aml(bp, aml_path, source="dify", input_path=input_path)
    return _compile_dify_blueprint(bp, is_app, graph_name=graph_name, options=options)


def load_graph_from_dify_yaml(
    source: str | Path | bytes,
    *,
    graph_name: str | None = None,
    options: DifyCompileOptions | None = None,
    graph_design_path: str | Path | bool | None = None,
    aml_path: str | Path | bool | None = None,
) -> Graph:
    """Load a Dify workflow YAML export and compile it into an executable graph."""
    doc, input_path = load_mapping_source(source, label="Dify document")
    return _load_graph_from_dify(
        doc,
        input_path=input_path,
        graph_name=graph_name,
        options=options,
        graph_design_path=graph_design_path,
        aml_path=aml_path,
    )


def load_graph_from_dify_dict(
    doc: dict,
    *,
    graph_name: str | None = None,
    options: DifyCompileOptions | None = None,
    graph_design_path: str | Path | bool | None = None,
    aml_path: str | Path | bool | None = None,
) -> Graph:
    """Parse a Dify workflow mapping and compile it into a graph."""
    return _load_graph_from_dify(
        doc,
        input_path=None,
        graph_name=graph_name,
        options=options,
        graph_design_path=graph_design_path,
        aml_path=aml_path,
    )


def dify_document_to_graph_design(doc: dict, *, source: str = "dify") -> dict:
    """Return a deprecated ``{graph_design: ...}`` document through the AML path."""
    bp, _ = _document_to_blueprint(doc)
    return blueprint_to_graph_design_document_via_aml(bp, source=source)


def dify_document_to_aml(doc: dict, *, source: str = "dify") -> str:
    """Return a Visualizer-previewable AML document from a Dify export."""
    bp, _ = _document_to_blueprint(doc)
    return blueprint_to_aml_document(bp, source=source)
