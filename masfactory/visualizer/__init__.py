"""
MASFactory Visualizer (runtime integration)

This package provides an optional runtime/UI bridge for the `masfactory-visualizer` VS Code extension.

Public API (recommended):
- `masfactory.visualizer.connect()` / `masfactory.visualizer.get_bridge()` / `VisualizerClient`

Implementation detail:
The bridge is enabled via environment variables injected by the extension host
(`MASFACTORY_VISUALIZER_PORT`, etc.). Call-sites should not depend on those env vars directly.

- MASFACTORY_VISUALIZER_PORT: required (WebSocket server port)
- MASFACTORY_VISUALIZER_MODE: optional ("debug" enables active mode; default is "run")

The integration is best-effort and must never break normal MASFactory execution when the
extension is not present.
"""

# Some runners (notably pytest in importlib mode) may load this file as a plain module.
# Ensure it still behaves like a package so `masfactory.visualizer.*` submodules can import.
if "__path__" not in globals():  # pragma: no cover
    from pathlib import Path

    __path__ = [str(Path(__file__).resolve().parent)]

from .client import (  # noqa: F401
    VISUALIZER_PROTOCOL_VERSION,
    VisualizerBridge,
    VisualizerClient,
    VisualizerOpenFileOptions,
    connect,
    connect_bridge,
    get_bridge,
    get_client,
    is_available,
)
from .runtime import VisualizerRuntime, get_visualizer_runtime  # noqa: F401
