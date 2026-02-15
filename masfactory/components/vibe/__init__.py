"""
vibe_demo (simplified)
======================

This directory is a *demo* implementation of a decoupled Vibe architecture.

Goals:
- Do NOT touch the verified `masfactory/components/vibe/` implementation.
- Keep the design minimal:
  - A workflow object generates + parses `graph_design` (workflow owns parsing).
  - VibeGraph orchestrates cache -> workflow -> parse -> compile.
"""

from .vibe_graph import VibeGraph

__all__ = [
    "VibeGraph",
]
