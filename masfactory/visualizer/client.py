from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from .runtime import VISUALIZER_ENABLED, VisualizerRuntime, get_visualizer_runtime

VISUALIZER_PROTOCOL_VERSION = 1

VisualizerView = Literal["auto", "preview", "vibe"]

@dataclass(frozen=True)
class VisualizerOpenFileOptions:
    """Options for opening a file in the Visualizer UI."""

    file_path: str
    view: VisualizerView = "auto"
    # Whether to reveal/show the Visualizer webview panel.
    reveal: bool = True
    # Whether to keep editor focus when opening the document.
    preserve_focus: bool | None = None

class VisualizerClient:
    """
    A small, stable facade for interacting with the `masfactory-visualizer` VS Code extension.

    Design goals:
    - Keep call-sites simple: `visualizer.connect()`, `visualizer.request_user_input()`, `visualizer.open_file()`
    - Best-effort only: never break normal execution when Visualizer is absent.
    - Loose coupling: call-sites don't depend on WS message shapes.
    """

    def __init__(self, runtime: VisualizerRuntime):
        """Create a VisualizerClient facade.

        Args:
            runtime: Connected VisualizerRuntime instance used for transport.
        """
        self._runtime = runtime

    @property
    def pid(self) -> int | None:
        try:
            v = getattr(self._runtime, "_pid", None)
            return int(v) if isinstance(v, int) else None
        except Exception:
            return None

    @property
    def mode(self) -> str:
        try:
            return str(getattr(self._runtime, "mode", "unknown") or "unknown")
        except Exception:
            return "unknown"

    def connect(self, *, timeout_s: float = 2.0) -> bool:
        try:
            self._runtime.start()
            return self._runtime.wait_connected(timeout_s=max(0.0, float(timeout_s)))
        except Exception:
            return False

    def is_connected(self) -> bool:
        try:
            return self._runtime.is_connected()
        except Exception:
            return False

    # Graph lifecycle APIs for framework internals.
    def attach_graph(self, root_graph: object) -> None:
        """
        Attach Visualizer runtime hooks to a built RootGraph.

        This should be called once after the graph is fully built (nodes/edges exist),
        so we don't need to re-register hooks per-invocation.
        """
        try:
            from .runtime_hooks import install_root_graph_runtime_hooks

            self.set_active_graph(root_graph)
            install_root_graph_runtime_hooks(root_graph, self)
        except Exception:
            return

    def begin_run(self, root_graph: object, *, input: dict[str, object] | None = None) -> None:
        """
        Prepare Visualizer runtime state for a new run without re-installing hooks.
        """
        try:
            from .runtime_hooks import reset_root_graph_runtime_hooks

            reset_root_graph_runtime_hooks(root_graph, self)
            if isinstance(input, dict):
                self.log("info", f"[run] start graph={getattr(root_graph, 'name', 'unknown')} inputKeys={list(input.keys())}")
            else:
                self.log("info", f"[run] start graph={getattr(root_graph, 'name', 'unknown')}")
        except Exception:
            return

    def end_run(self, root_graph: object, *, output: dict[str, object] | None = None) -> None:
        """Report the end of a run to the Visualizer (best-effort).

        Args:
            root_graph: RootGraph instance that just completed.
            output: Optional exit payload to summarize in logs.
        """
        try:
            if isinstance(output, dict):
                self.log("info", f"[run] done graph={getattr(root_graph, 'name', 'unknown')} outputKeys={list(output.keys())}")
            else:
                self.log("info", f"[run] done graph={getattr(root_graph, 'name', 'unknown')}")
        except Exception:
            return

    # Runtime/telemetry APIs for framework internals.
    def set_active_graph(self, root_graph: object) -> None:
        try:
            self._runtime.set_active_graph(root_graph)
        except Exception:
            return

    def log(self, level: str, message: str) -> None:
        try:
            self._runtime.log(level, message)
        except Exception:
            return

    def node_start(self, node: object, inputs: dict[str, object]) -> object | None:
        """Notify the Visualizer that a node is about to execute.

        Args:
            node: Node object being executed.
            inputs: Input payload passed into the node.

        Returns:
            An opaque context object produced by the runtime, or None on failure. The returned
            context can be passed back into `node_end()` / `node_error()`.
        """
        try:
            return self._runtime.node_start(node, inputs)
        except Exception:
            return None

    def node_end(self, ctx: object | None, outputs: dict[str, object], node: object | None = None) -> None:
        """Notify the Visualizer that a node finished successfully.

        Args:
            ctx: Context returned by `node_start()` (may be None).
            outputs: Node output payload.
            node: Optional node object when context is unavailable.
        """
        try:
            self._runtime.node_end(ctx, outputs, node=node)
        except Exception:
            return

    def node_error(self, ctx: object | None, err: BaseException) -> None:
        """Notify the Visualizer that a node execution failed.

        Args:
            ctx: Context returned by `node_start()` (may be None).
            err: Exception raised by node execution.
        """
        try:
            self._runtime.node_error(ctx, err)
        except Exception:
            return

    def flow_edge_send(
        self,
        sender: object,
        receiver: object,
        *,
        edge_keys: dict[str, object] | None = None,
        message: dict[str, object] | None = None,
    ) -> None:
        """Report an edge send event to the Visualizer.

        Args:
            sender: Sender node object.
            receiver: Receiver node object.
            edge_keys: Optional edge key mapping for the send.
            message: Optional message payload being sent.
        """
        try:
            self._runtime.flow_edge_send(sender, receiver, edge_keys=edge_keys, message=message)
        except Exception:
            return

    def flow_attr_pull(
        self,
        node: object,
        *,
        scope: str | None = None,
        keys: list[str] | None = None,
        values: dict[str, object] | None = None,
        total_keys: int | None = None,
        truncated: bool = False,
    ) -> None:
        """Report an attribute pull event to the Visualizer.

        Args:
            node: Node object that performed the pull.
            scope: Optional scope label.
            keys: Optional list of pulled keys (may be truncated).
            values: Optional snapshot of pulled values (may be truncated).
            total_keys: Total number of keys pulled before truncation (if known).
            truncated: Whether the keys/values were truncated to limit payload size.
        """
        try:
            self._runtime.flow_attr_pull(
                node,
                scope=scope,
                keys=keys,
                values=values,
                total_keys=total_keys,
                truncated=truncated,
            )
        except Exception:
            return

    def flow_attr_push(
        self,
        node: object,
        *,
        scope: str | None = None,
        changes: dict[str, object] | None = None,
        total_keys: int | None = None,
        truncated: bool = False,
    ) -> None:
        """Report an attribute push event to the Visualizer.

        Args:
            node: Node object that performed the push.
            scope: Optional scope label.
            changes: Optional mapping of changed keys -> new values (may be truncated).
            total_keys: Total number of changed keys before truncation (if known).
            truncated: Whether the changes payload was truncated to limit size.
        """
        try:
            self._runtime.flow_attr_push(
                node,
                scope=scope,
                changes=changes,
                total_keys=total_keys,
                truncated=truncated,
            )
        except Exception:
            return

    def request_user_input(
        self,
        *,
        node: str,
        prompt: str,
        field: str | None = None,
        description: str | None = None,
        timeout_s: float | None = None,
        meta: dict[str, object] | None = None,
    ) -> str | None:
        """Request user input via the Visualizer UI.

        Args:
            node: Node name that initiated the request.
            prompt: Prompt text shown to the user.
            field: Optional field name associated with the prompt (for structured workflows).
            description: Optional extra description shown in the UI.
            timeout_s: Optional timeout in seconds.
            meta: Optional extra metadata attached to the request.

        Returns:
            User response string, or None if Visualizer is unavailable or the request times out.
        """
        try:
            resp = self._runtime.request_interaction(
                node=node,
                prompt=prompt,
                field=field,
                description=description,
                timeout_s=timeout_s,
                meta=meta,
            )
        except Exception:
            return None
        if resp is None:
            return None
        return resp if isinstance(resp, str) else str(resp)

    def open_file(self, options: VisualizerOpenFileOptions) -> bool:
        """Open a file in VS Code and optionally reveal the Visualizer panel.

        Args:
            options: Open-file options (path, target view, focus behavior).

        Returns:
            True if the request was sent, otherwise False.
        """
        file_path = options.file_path if isinstance(options.file_path, str) else ""
        file_path = file_path.strip()
        if not file_path:
            return False

        view: VisualizerView = options.view if options.view in ("auto", "preview", "vibe") else "auto"

        preserve_focus = options.preserve_focus
        if preserve_focus is None:
            # Default UX: Vibe editing happens inside Visualizer, so keep focus there.
            preserve_focus = view == "vibe"

        payload: dict[str, object] = {
            "type": "UI_OPEN_FILE",
            "visualizerProtocolVersion": VISUALIZER_PROTOCOL_VERSION,
            "filePath": os.path.abspath(file_path),
            "view": view,
            "reveal": bool(options.reveal),
            "preserveFocus": bool(preserve_focus),
        }
        return self._runtime.send_message(payload, require_connection=True)

_CLIENT_SINGLETON: VisualizerClient | None = None

VisualizerBridge = VisualizerClient

def is_available() -> bool:
    return bool(VISUALIZER_ENABLED)

def get_client() -> VisualizerClient | None:
    """
    Return a client wrapper if Visualizer env vars are present; does not attempt to connect.
    """
    runtime = get_visualizer_runtime()
    if runtime is None:
        return None
    return VisualizerClient(runtime)

def connect(*, timeout_s: float = 2.0) -> VisualizerClient | None:
    """
    Establish a best-effort connection to the Visualizer extension host.

    Returns a `VisualizerClient` on success, otherwise None.
    """
    global _CLIENT_SINGLETON

    runtime = get_visualizer_runtime()
    if runtime is None:
        return None

    client = _CLIENT_SINGLETON or VisualizerClient(runtime)
    _CLIENT_SINGLETON = client

    if not client.connect(timeout_s=timeout_s):
        return None
    return client

def get_bridge() -> VisualizerBridge | None:
    """Return a Visualizer bridge without forcing a connection.

    This is an alias for `get_client()` kept for naming consistency with older code.
    It only returns a bridge when the Visualizer runtime is enabled via environment.
    """
    return get_client()

def connect_bridge(*, timeout_s: float = 2.0) -> VisualizerBridge | None:
    """Return a connected Visualizer bridge (best-effort).

    This is an alias for `connect()` kept for naming consistency with older code.

    Args:
        timeout_s: Connection timeout in seconds.
    """
    return connect(timeout_s=timeout_s)
