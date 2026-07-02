from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .v0_2 import AmlDocument
from .v0_2 import aml_to_graph_design as aml_to_graph_design_v0_2
from .v0_2 import graph_design_to_aml_document as graph_design_to_aml_document_v0_2
from .v0_2 import parse_aml_document as parse_aml_document_v0_2
from .v0_2 import validate_aml_document as validate_aml_document_v0_2

AML_VERSION = "0.2"
SUPPORTED_AML_VERSIONS = ("0.2",)

_AML_VERSION_RE = re.compile(r"<\s*aml\b[^>]*\bversion\s*=\s*(['\"])(.*?)\1", re.IGNORECASE | re.DOTALL)


def _read_text(source: str | Path) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    text = str(source)
    if text.lstrip().startswith("<"):
        return text
    path = Path(text)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return text


def detect_aml_version(source: str | Path) -> str:
    """Detect the AML version from text or a file path.

    AML documents created before explicit versioning are treated as v0.2 so the
    first public AML design has a stable compatibility baseline.
    """
    text = _read_text(source)
    match = _AML_VERSION_RE.search(text)
    version = (match.group(2).strip() if match else "") or AML_VERSION
    if version not in SUPPORTED_AML_VERSIONS:
        raise ValueError(f"Unsupported AML version '{version}'. Supported versions: {SUPPORTED_AML_VERSIONS}")
    return version


def aml_to_graph_design(source: str | Path, *, strict: bool = False) -> dict[str, Any]:
    """Convert AML into the legacy graph_design shape used by existing adapters."""
    version = detect_aml_version(source)
    if version == "0.2":
        return aml_to_graph_design_v0_2(source, strict=strict)
    raise ValueError(f"Unsupported AML version '{version}'")


def parse_aml_document(source: str | Path, *, strict: bool = False) -> AmlDocument:
    """Parse AML into the versioned AML-native document model."""
    version = detect_aml_version(source)
    if version == "0.2":
        return parse_aml_document_v0_2(source, strict=strict)
    raise ValueError(f"Unsupported AML version '{version}'")


def validate_aml_document(document: AmlDocument) -> None:
    """Validate an AML-native document model."""
    version = (document.version or AML_VERSION).strip()
    if version == "0.2":
        validate_aml_document_v0_2(document)
        return
    raise ValueError(f"Unsupported AML version '{version}'")


def graph_design_to_aml_document(
    graph_design: dict[str, Any],
    *,
    document_id: str = "masfactory.compatibility.graph",
    root_graph_id: str = "root",
    source: str | None = None,
) -> str:
    """Serialize a graph_design object as an AML v0.2 document."""
    return graph_design_to_aml_document_v0_2(
        graph_design,
        document_id=document_id,
        root_graph_id=root_graph_id,
        source=source,
    )


def graph_design_to_aml(
    graph_design: dict[str, Any],
    *,
    document_id: str = "masfactory.compatibility.graph",
    root_graph_id: str = "root",
    source: str | None = None,
) -> str:
    """Alias for graph_design_to_aml_document."""
    return graph_design_to_aml_document(
        graph_design,
        document_id=document_id,
        root_graph_id=root_graph_id,
        source=source,
    )
