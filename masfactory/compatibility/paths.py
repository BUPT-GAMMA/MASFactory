from __future__ import annotations

from pathlib import Path
from typing import Any

from masfactory.compatibility.common.names import slugify_node_name

_COMPATIBILITY_ROOT = Path(__file__).resolve().parent
COMPATIBILITY_OUT_DIR = _COMPATIBILITY_ROOT / "out"


def compatibility_out_dir(*, mkdir: bool = False) -> Path:
    """Directory for compatibility-layer artifacts (``graph_design.json``, etc.)."""
    if mkdir:
        COMPATIBILITY_OUT_DIR.mkdir(parents=True, exist_ok=True)
    return COMPATIBILITY_OUT_DIR


def default_graph_design_path(
    source: str,
    *,
    input_path: str | Path | None = None,
    stem: str | None = None,
) -> Path:
    """Default ``graph_design.json`` path under ``masfactory/compatibility/out/``."""
    if stem is not None:
        base = slugify_node_name(stem, fallback=source)
    elif input_path is not None:
        base = slugify_node_name(Path(input_path).stem, fallback=source)
    else:
        base = slugify_node_name(source, fallback="import")
    source_slug = slugify_node_name(source.replace("/", "_"), fallback="import")
    return compatibility_out_dir(mkdir=True) / f"{source_slug}_{base}_graph_design.json"


def default_aml_path(
    source: str,
    *,
    input_path: str | Path | None = None,
    stem: str | None = None,
) -> Path:
    """Default AML path under ``masfactory/compatibility/out/``."""
    if stem is not None:
        base = slugify_node_name(stem, fallback=source)
    elif input_path is not None:
        base = slugify_node_name(Path(input_path).stem, fallback=source)
    else:
        base = slugify_node_name(source, fallback="import")
    source_slug = slugify_node_name(source.replace("/", "_"), fallback="import")
    return compatibility_out_dir(mkdir=True) / f"{source_slug}_{base}.aml"


def resolve_graph_design_export_path(
    graph_design_path: str | Path | bool | None,
    *,
    source: str,
    input_path: str | Path | None = None,
    stem: str | None = None,
) -> Path | None:
    """Resolve where to write a preview ``graph_design.json``.

    - ``None`` / ``False``: do not write
    - ``True``: ``compatibility/out/{source}_{stem}_graph_design.json``
    - relative path: under ``compatibility/out/``
    - absolute path: use as given
    """
    if graph_design_path is None or graph_design_path is False:
        return None
    if graph_design_path is True:
        return default_graph_design_path(source, input_path=input_path, stem=stem)
    path = Path(graph_design_path)
    if path.is_absolute():
        return path
    return compatibility_out_dir(mkdir=True) / path


def resolve_aml_export_path(
    aml_path: str | Path | bool | None,
    *,
    source: str,
    input_path: str | Path | None = None,
    stem: str | None = None,
) -> Path | None:
    """Resolve where to write a preview AML document.

    - ``None`` / ``False``: do not write
    - ``True``: ``compatibility/out/{source}_{stem}.aml``
    - relative path: under ``compatibility/out/``
    - absolute path: use as given
    """
    if aml_path is None or aml_path is False:
        return None
    if aml_path is True:
        return default_aml_path(source, input_path=input_path, stem=stem)
    path = Path(aml_path)
    if path.is_absolute():
        return path
    return compatibility_out_dir(mkdir=True) / path


def maybe_export_graph_design(
    blueprint: Any,
    graph_design_path: str | Path | bool | None,
    *,
    source: str,
    input_path: str | Path | None = None,
    stem: str | None = None,
) -> Path | None:
    """Write legacy ``graph_design.json`` when ``graph_design_path`` requests it."""
    out_path = resolve_graph_design_export_path(
        graph_design_path,
        source=source,
        input_path=input_path,
        stem=stem,
    )
    if out_path is None:
        return None
    from masfactory.compatibility.common.aml_export import blueprint_to_graph_design_document_via_aml
    from masfactory.compatibility.common.graph_design_export import write_graph_design_json

    return write_graph_design_json(
        out_path,
        blueprint_to_graph_design_document_via_aml(blueprint, source=source),
    )


def maybe_export_aml(
    blueprint: Any,
    aml_path: str | Path | bool | None,
    *,
    source: str,
    input_path: str | Path | None = None,
    stem: str | None = None,
) -> Path | None:
    """Write an AML preview document when ``aml_path`` requests it."""
    out_path = resolve_aml_export_path(
        aml_path,
        source=source,
        input_path=input_path,
        stem=stem,
    )
    if out_path is None:
        return None
    from masfactory.compatibility.common.aml_export import export_aml_for_blueprint

    return export_aml_for_blueprint(blueprint, out_path, source=source)
