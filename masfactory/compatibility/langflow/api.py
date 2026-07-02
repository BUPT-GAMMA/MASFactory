from __future__ import annotations

from pathlib import Path

from masfactory.compatibility.common.aml_export import (
    blueprint_to_aml_document,
    blueprint_to_graph_design_document_via_aml,
    blueprint_to_graph_via_aml,
)
from masfactory.compatibility.common.loaders import load_mapping_source
from masfactory.compatibility.common.names import slugify_node_name
from masfactory.compatibility.langflow.parse import langflow_document_to_blueprint
from masfactory.compatibility.paths import maybe_export_aml, maybe_export_graph_design
from masfactory.compatibility.common.llm_options import LangflowCompileOptions
from masfactory.components.graphs.graph import Graph


def langflow_document_to_graph(
    doc: dict,
    *,
    graph_name: str = "langflow_import",
    options: LangflowCompileOptions | None = None,
    graph_design_path: str | Path | bool | None = None,
    aml_path: str | Path | bool | None = None,
    input_path: str | Path | None = None,
) -> Graph:
    bp = langflow_document_to_blueprint(doc)
    maybe_export_graph_design(bp, graph_design_path, source="langflow", input_path=input_path)
    maybe_export_aml(bp, aml_path, source="langflow", input_path=input_path)
    model = None
    if options is not None and (
        options.model_factory is not None
        or options.use_stub_llm
        or options.openai_api_key
        or options.openai_base_url
    ):
        model = options.resolve_model({"name": graph_name, "source": "langflow"})
    return blueprint_to_graph_via_aml(bp, graph_name=graph_name, source="langflow", model=model)


def langflow_document_to_graph_design(doc: dict, *, source: str = "langflow") -> dict:
    """Return a deprecated ``{graph_design: ...}`` document through the AML path."""
    bp = langflow_document_to_blueprint(doc)
    return blueprint_to_graph_design_document_via_aml(bp, source=source)


def langflow_document_to_aml(doc: dict, *, source: str = "langflow") -> str:
    """Return a Visualizer-previewable AML document from Langflow JSON."""
    bp = langflow_document_to_blueprint(doc)
    return blueprint_to_aml_document(bp, source=source)


def load_graph_from_langflow_json(
    source: str | Path | bytes,
    *,
    graph_name: str = "langflow_import",
    options: LangflowCompileOptions | None = None,
    graph_design_path: str | Path | bool | None = None,
    aml_path: str | Path | bool | None = None,
) -> Graph:
    """Load a Langflow JSON export and return an executable MASFactory graph."""
    doc, input_path = load_mapping_source(source, label="Langflow JSON")
    name = graph_name
    if name == "langflow_import" and input_path is not None:
        name = f"lf_{input_path.stem}"
    name = slugify_node_name(name, fallback="langflow_import")
    return langflow_document_to_graph(
        doc,
        graph_name=name,
        options=options,
        graph_design_path=graph_design_path,
        aml_path=aml_path,
        input_path=input_path,
    )
