"""
vibe_demo (simplified)
======================

This directory is a *demo* implementation of a decoupled Vibe architecture.

Goals:
- Do NOT touch the verified `masfactory/components/vibe/` implementation.
- Keep the design minimal:
  - A workflow object generates AML.
  - VibeGraph orchestrates AML cache -> workflow -> parse -> compile.
  - LegacyVibeGraph remains available for graph_design migration.
"""

from .legacy_vibe_graph import LegacyVibeGraph
from .vibe_graph import VibeGraph

__all__ = [
    "LegacyVibeGraph",
    "VibeGraph",
]
