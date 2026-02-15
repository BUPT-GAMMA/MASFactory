from __future__ import annotations

import json
import os
import queue
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .ws import (
    WebSocketError,
    ws_handshake,
    ws_send_close,
    ws_send_pong,
    ws_send_text,
    ws_try_decode_frame,
)

# Public flag for cheap fast-path checks in hot code paths.
VISUALIZER_ENABLED: bool = bool(os.environ.get("MASFACTORY_VISUALIZER_PORT"))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except Exception:
            return None
    return None


def _as_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


@dataclass
class _NodeRunContext:
    """Execution context captured at node start and used to compute end metrics."""

    node_name: str
    run_id: str
    started_ms: int
    token_before_in: int | None = None
    token_before_out: int | None = None


@dataclass
class _PendingInteraction:
    """Pending human interaction request tracked until a response arrives."""

    request_id: str
    created_ms: int
    event: threading.Event
    response: object | None = None


class VisualizerRuntime:
    """
    MASFactory Visualizer runtime bridge.

    - Connects to the VS Code extension host via WebSocket (MASFACTORY_VISUALIZER_PORT).
    - Run mode: sends heartbeats; detailed data only after SUBSCRIBE.
    - Debug mode: sends full graph immediately and streams events.
    """

    def __init__(self, host: str, port: int, mode: str):
        """Create a VisualizerRuntime bridge.

        Args:
            host: Visualizer WebSocket server host.
            port: Visualizer WebSocket server port.
            mode: Runtime mode (`run` or `debug`).
        """
        self._host = host
        self._port = port
        self._mode = (mode or "run").lower()
        self._pid = os.getpid()

        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self._connected = False
        self._subscribed = False

        self._graph_name: str | None = None
        self._graph_payload: dict[str, object] | None = None
        self._graph_version = 0
        self._last_sent_graph_version = -1
        self._root_entry_obj: object | None = None
        self._root_exit_obj: object | None = None

        self._outq: "queue.Queue[dict[str, object]]" = queue.Queue(maxsize=5000)
        self._history_events: list[dict[str, object]] = []
        self._history_dropped = 0
        self._history_truncated_fields = 0

        # Tune: keep a bounded history so late subscribers can reconstruct execution state.
        self._history_max_events = 1200
        self._history_max_str = 5000

        # Human-in-the-loop interaction (request/response)
        self._pending_interactions: dict[str, _PendingInteraction] = {}

    @property
    def mode(self) -> str:
        return self._mode

    def is_debug(self) -> bool:
        return self._mode == "debug"

    def is_streaming(self) -> bool:
        # Debug is active-mode by definition.
        if self.is_debug():
            return True
        return self._subscribed

    def is_connected(self) -> bool:
        with self._lock:
            return bool(self._connected)

    def wait_connected(self, timeout_s: float = 2.0) -> bool:
        if timeout_s <= 0:
            return self.is_connected()
        deadline = time.time() + float(timeout_s)
        while time.time() < deadline:
            if self.is_connected():
                return True
            time.sleep(0.05)
        return self.is_connected()

    def request_interaction(
        self,
        *,
        node: str,
        prompt: str,
        field: str | None = None,
        description: str | None = None,
        timeout_s: float | None = None,
        meta: dict[str, object] | None = None,
    ) -> object | None:
        """
        Ask the MASFactory Visualizer UI for user input and block until a response arrives.

        Returns the raw response payload (usually a string). If Visualizer is not connected
        or the request times out, returns None.
        """
        if not node or not prompt:
            return None
        self.start()
        if not self.wait_connected(timeout_s=2.0):
            return None

        request_id = uuid.uuid4().hex
        pending = _PendingInteraction(
            request_id=request_id,
            created_ms=_now_ms(),
            event=threading.Event(),
        )
        with self._lock:
            self._pending_interactions[request_id] = pending

        payload: dict[str, object] = {
            "type": "INTERACT_REQUEST",
            "requestId": request_id,
            "node": node,
            "prompt": str(prompt),
            "ts": _now_ms(),
        }
        if field:
            payload["field"] = str(field)
        if description:
            payload["description"] = str(description)
        if isinstance(meta, dict) and meta:
            payload["meta"] = self._safe_for_history(meta)

        # Always enqueue interaction requests, even when not subscribed (run mode).
        try:
            self._outq.put(payload, timeout=0.2)
        except queue.Full:
            with self._lock:
                self._pending_interactions.pop(request_id, None)
            return None

        if timeout_s is None:
            pending.event.wait()
        else:
            pending.event.wait(timeout=float(timeout_s))

        with self._lock:
            p = self._pending_interactions.pop(request_id, None)
        if not p:
            return None
        if not p.event.is_set():
            return None
        return p.response

    def _safe_for_history(self, value: object, *, depth: int = 5) -> object:
        """
        Best-effort JSON-friendly conversion with truncation to keep history bounded.

        - Limits recursion depth and container sizes.
        - Truncates long strings.
        - Falls back to str(value) when needed.
        """

        def _truncate(s: str) -> str:
            if len(s) <= self._history_max_str:
                return s
            self._history_truncated_fields += 1
            return s[: self._history_max_str] + "…(truncated)"

        if value is None or isinstance(value, (int, float, bool)):
            return value
        if isinstance(value, str):
            return _truncate(value)
        if depth <= 0:
            return _truncate(str(value))
        if isinstance(value, dict):
            out: dict[str, object] = {}
            i = 0
            for k, v in value.items():
                if i >= 50:
                    self._history_truncated_fields += 1
                    out["__masfactory_visualizer_truncated__"] = True
                    out["__masfactory_visualizer_items__"] = i
                    break
                out[str(k)] = self._safe_for_history(v, depth=depth - 1)
                i += 1
            return out
        if isinstance(value, (list, tuple, set)):
            out_list: list[object] = []
            for i, v in enumerate(value):
                if i >= 50:
                    self._history_truncated_fields += 1
                    out_list.append("…(truncated)")
                    break
                out_list.append(self._safe_for_history(v, depth=depth - 1))
            return out_list
        return _truncate(str(value))

    def _record_history(self, msg: dict[str, object]) -> None:
        with self._lock:
            self._history_events.append(msg)
            if len(self._history_events) > self._history_max_events:
                overflow = len(self._history_events) - self._history_max_events
                if overflow > 0:
                    self._history_events = self._history_events[overflow:]
                    self._history_dropped += overflow

    def _take_history_snapshot(self) -> tuple[list[dict[str, object]], int, int]:
        with self._lock:
            if not self._history_events:
                return [], 0, 0
            events = list(self._history_events)
            dropped = int(self._history_dropped)
            truncated = int(self._history_truncated_fields)
            self._history_events.clear()
            self._history_dropped = 0
            self._history_truncated_fields = 0
        return events, dropped, truncated

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="masfactory-visualizer-runtime", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.0)

    def set_active_graph(self, root_graph: object) -> None:
        """
        Update current graph context and prepare graph payload.
        """
        try:
            from .serialize import serialize_root_graph

            graph_name = getattr(root_graph, "name", None)
            if not isinstance(graph_name, str) or not graph_name:
                graph_name = "unknown"

            payload = serialize_root_graph(root_graph).graph
        except Exception as e:
            graph_name = getattr(root_graph, "name", "unknown")
            payload = {"nodes": ["entry", "exit"], "nodeTypes": {"entry": "entry", "exit": "exit"}, "edges": [], "warnings": [str(e)]}

        with self._lock:
            self._graph_name = graph_name
            self._graph_payload = payload
            self._graph_version += 1
            # Keep a handle to RootGraph entry/exit for stable node id mapping ("entry"/"exit").
            self._root_entry_obj = getattr(root_graph, "_entry", None)
            self._root_exit_obj = getattr(root_graph, "_exit", None)

        self.start()

    def _resolve_node_id(self, node: object) -> str | None:
        if node is None:
            return None
        with self._lock:
            if self._root_entry_obj is not None and node is self._root_entry_obj:
                return "entry"
            if self._root_exit_obj is not None and node is self._root_exit_obj:
                return "exit"
        name = getattr(node, "name", None)
        if isinstance(name, str) and name:
            return name
        return None

    def node_start(self, node: object, inputs: dict[str, object]) -> _NodeRunContext | None:
        """Record a node-start event.

        Args:
            node: Node instance (or internal node object) being executed.
            inputs: Input payload passed to the node.

        Returns:
            A `_NodeRunContext` used to later record end/error events, or `None` if the node
            cannot be resolved to a stable node id.
        """
        node_name = self._resolve_node_id(node)
        if not node_name:
            return None

        token_before_in = None
        token_before_out = None
        try:
            model = getattr(node, "model", None)
            tracker = getattr(model, "token_tracker", None) if model else None
            token_before_in = int(getattr(tracker, "total_input_usage", 0)) if tracker else None
            token_before_out = int(getattr(tracker, "total_output_usage", 0)) if tracker else None
        except Exception:
            token_before_in = None
            token_before_out = None

        run_id = f"{self._pid}-{uuid.uuid4().hex[:10]}"
        ts = _now_ms()

        payload: dict[str, object] = {
            "type": "NODE_EVENT",
            "event": "start",
            "node": node_name,
            "ts": ts,
            "runId": run_id,
            "inputs": self._safe_for_history(inputs if isinstance(inputs, dict) else {"input": inputs}),
        }
        if self.is_streaming():
            self._enqueue(payload)
        else:
            self._record_history(payload)
        return _NodeRunContext(
            node_name=node_name,
            run_id=run_id,
            started_ms=ts,
            token_before_in=token_before_in,
            token_before_out=token_before_out,
        )

    def node_end(self, ctx: _NodeRunContext | None, outputs: dict[str, object], node: object | None = None) -> None:
        """Record a node-end event and attach basic metrics when available.

        Args:
            ctx: Context returned by `node_start()`. If None, this is a no-op.
            outputs: Output payload produced by the node.
            node: Optional node instance used to extract token usage deltas.
        """
        if not ctx:
            return

        metrics: dict[str, Any] = {}
        if node is not None:
            try:
                model = getattr(node, "model", None)
                tracker = getattr(model, "token_tracker", None) if model else None
                if tracker and ctx.token_before_in is not None and ctx.token_before_out is not None:
                    after_in = int(getattr(tracker, "total_input_usage", 0))
                    after_out = int(getattr(tracker, "total_output_usage", 0))
                    din = max(0, after_in - ctx.token_before_in)
                    dout = max(0, after_out - ctx.token_before_out)
                    metrics["token_usage"] = {
                        "prompt_tokens": din,
                        "completion_tokens": dout,
                        "total_tokens": din + dout,
                    }
            except Exception:
                pass

        ended = _now_ms()
        metrics["duration_ms"] = max(0, ended - ctx.started_ms)

        payload: dict[str, Any] = {
            "type": "NODE_EVENT",
            "event": "end",
            "node": ctx.node_name,
            "ts": ended,
            "runId": ctx.run_id,
            "outputs": self._safe_for_history(outputs if isinstance(outputs, dict) else {"output": outputs}),
        }
        if metrics:
            payload["metrics"] = self._safe_for_history(metrics)
        if self.is_streaming():
            self._enqueue(payload)
        else:
            self._record_history(payload)

    def node_error(self, ctx: _NodeRunContext | None, err: BaseException) -> None:
        """Record a node-error event.

        Args:
            ctx: Context returned by `node_start()`. If None, this is a no-op.
            err: Raised exception.
        """
        if not ctx:
            return
        payload = {
            "type": "NODE_EVENT",
            "event": "error",
            "node": ctx.node_name,
            "ts": _now_ms(),
            "runId": ctx.run_id,
            "error": self._safe_for_history(f"{type(err).__name__}: {err}"),
        }
        if self.is_streaming():
            self._enqueue(payload)
        else:
            self._record_history(payload)

    def flow_edge_send(
        self,
        sender: object,
        receiver: object,
        *,
        edge_keys: dict[str, object] | None = None,
        message: dict[str, object] | None = None,
    ) -> None:
        """Record an edge-send flow event.

        Args:
            sender: Sender node.
            receiver: Receiver node.
            edge_keys: Optional edge key mapping (used to render key labels/details).
            message: Optional message payload snapshot.
        """
        sender_id = self._resolve_node_id(sender)
        receiver_id = self._resolve_node_id(receiver)
        if not sender_id or not receiver_id:
            return

        keys: list[str] = []
        keys_details: dict[str, object] | None = None
        if isinstance(edge_keys, dict):
            keys = [str(k) for k in edge_keys.keys()]
            keys_details = {str(k): edge_keys.get(k) for k in edge_keys.keys()}

        payload: dict[str, object] = {
            "type": "FLOW",
            "kind": "EDGE_SEND",
            "ts": _now_ms(),
            "from": sender_id,
            "to": receiver_id,
        }
        if keys:
            payload["keys"] = keys
        if keys_details:
            payload["keysDetails"] = self._safe_for_history(keys_details)
        if isinstance(message, dict) and message:
            payload["message"] = self._safe_for_history(message)

        if self.is_streaming():
            self._enqueue(payload)
        else:
            self._record_history(payload)

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
        """Record an attribute-pull flow event.

        Args:
            node: Node performing the pull.
            scope: Optional scope label.
            keys: Pulled keys.
            values: Optional sampled values for pulled keys.
            total_keys: Total number of keys pulled when only a subset is included.
            truncated: Whether values were truncated for transport/history bounds.
        """
        node_id = self._resolve_node_id(node)
        if not node_id:
            return
        payload: dict[str, object] = {
            "type": "FLOW",
            "kind": "ATTR_PULL",
            "ts": _now_ms(),
            "node": node_id,
        }
        if scope:
            payload["scope"] = scope
        if keys:
            payload["keys"] = [str(k) for k in keys]
        if isinstance(total_keys, int) and total_keys >= 0:
            payload["totalKeys"] = total_keys
        if truncated:
            payload["truncated"] = True
        if isinstance(values, dict) and values:
            payload["values"] = self._safe_for_history(values)

        if self.is_streaming():
            self._enqueue(payload)
        else:
            self._record_history(payload)

    def flow_attr_push(
        self,
        node: object,
        *,
        scope: str | None = None,
        changes: dict[str, object] | None = None,
        total_keys: int | None = None,
        truncated: bool = False,
    ) -> None:
        """Record an attribute-push flow event.

        Args:
            node: Node performing the push.
            scope: Optional scope label.
            changes: Pushed key/value changes.
            total_keys: Total number of keys pushed when only a subset is included.
            truncated: Whether values were truncated for transport/history bounds.
        """
        node_id = self._resolve_node_id(node)
        if not node_id:
            return
        if not changes:
            return

        payload: dict[str, object] = {
            "type": "FLOW",
            "kind": "ATTR_PUSH",
            "ts": _now_ms(),
            "node": node_id,
            "changes": self._safe_for_history(changes),
        }
        if scope:
            payload["scope"] = scope
        if isinstance(total_keys, int) and total_keys >= 0:
            payload["totalKeys"] = total_keys
        if truncated:
            payload["truncated"] = True

        if self.is_streaming():
            self._enqueue(payload)
        else:
            self._record_history(payload)

    def log(self, level: str, message: str) -> None:
        payload = {
            "type": "LOG",
            "level": str(level or "info"),
            "message": str(message or ""),
            "ts": _now_ms(),
        }
        if self.is_streaming():
            self._enqueue(payload)
        else:
            self._record_history(payload)

    def send_message(
        self,
        payload: dict[str, object],
        *,
        require_connection: bool = True,
        connect_timeout_s: float = 2.0,
        enqueue_timeout_s: float = 0.2,
    ) -> bool:
        """
        Best-effort one-way message send to the Visualizer extension host.

        - Never throws (returns False on failure)
        - Uses the same WS channel as runtime tracing
        - Messages are sent regardless of subscription state (run mode)
        """
        if not isinstance(payload, dict) or not payload:
            return False

        try:
            self.start()
        except Exception:
            return False

        if require_connection:
            try:
                if not self.wait_connected(timeout_s=max(0.0, float(connect_timeout_s))):
                    return False
            except Exception:
                return False

        try:
            self._outq.put(payload, timeout=max(0.0, float(enqueue_timeout_s)))
            return True
        except Exception:
            return False

    def _enqueue(self, msg: dict[str, Any]) -> None:
        try:
            self._outq.put_nowait(msg)
        except queue.Full:
            # Drop to avoid blocking MASFactory execution.
            pass

    def _drain_outq(self, limit: int = 200) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for _ in range(limit):
            try:
                items.append(self._outq.get_nowait())
            except queue.Empty:
                break
        return items

    def _should_send_graph_now(self) -> bool:
        if self.is_debug():
            return True
        return self._subscribed

    def _run(self) -> None:
        last_hb = 0.0
        reconnect_delay = 0.25

        while not self._stop.is_set():
            try:
                with self._lock:
                    host = self._host
                    port = self._port
                    mode = self._mode
                    graph_name = self._graph_name or "unknown"
                sock = socket.create_connection((host, port), timeout=3)
                try:
                    ws_handshake(sock, host, port)
                    sock.settimeout(0.05)
                    with self._lock:
                        self._connected = True

                    ws_send_text(
                        sock,
                        json.dumps(
                            {"type": "HELLO", "pid": self._pid, "graphName": graph_name, "mode": mode}
                        ),
                    )

                    buf = b""
                    last_hb = 0.0
                    self._subscribed = False
                    reconnect_delay = 0.25

                    while not self._stop.is_set():
                        now = time.time()

                        # Heartbeat (always)
                        if now - last_hb >= 0.5:
                            with self._lock:
                                graph_name = self._graph_name or "unknown"
                                mode = self._mode
                            ws_send_text(
                                sock,
                                json.dumps(
                                    {
                                        "type": "HEARTBEAT",
                                        "pid": self._pid,
                                        "graphName": graph_name,
                                        "mode": mode,
                                    }
                                ),
                            )
                            last_hb = now

                        # Send queued messages
                        for msg in self._drain_outq():
                            ws_send_text(sock, json.dumps(msg, ensure_ascii=False, default=str))

                        # Send graph lazily (run mode on subscribe; debug mode always)
                        with self._lock:
                            gv = self._graph_version
                            payload = self._graph_payload
                        if (
                            payload is not None
                            and gv != self._last_sent_graph_version
                            and self._should_send_graph_now()
                        ):
                            ws_send_text(sock, json.dumps({"type": "GRAPH", "graph": payload}))
                            self._last_sent_graph_version = gv

                        # Read inbound frames
                        try:
                            chunk = sock.recv(4096)
                            if chunk:
                                buf += chunk
                        except socket.timeout:
                            pass

                        while True:
                            decoded = ws_try_decode_frame(buf)
                            if not decoded:
                                break
                            frame, buf = decoded
                            if frame.opcode == 0x8:
                                raise WebSocketError("server closed")
                            if frame.opcode == 0x9:
                                ws_send_pong(sock, frame.payload)
                                continue
                            if frame.opcode != 0x1:
                                continue
                            try:
                                msg = json.loads(frame.payload.decode("utf-8"))
                            except Exception:
                                continue
                            typ = str(msg.get("type", "")).upper()
                            if typ == "SUBSCRIBE":
                                # When transitioning to subscribed, flush buffered history so the UI
                                # can reconstruct what happened before the user opened the view.
                                was = self._subscribed
                                self._subscribed = True
                                if not was:
                                    events, dropped, truncated = self._take_history_snapshot()
                                    if events:
                                        ws_send_text(
                                            sock,
                                            json.dumps(
                                                {
                                                    "type": "HISTORY",
                                                    "events": events,
                                                    "dropped": dropped,
                                                    "truncated": truncated,
                                                },
                                                ensure_ascii=False,
                                                default=str,
                                            ),
                                        )
                            elif typ == "UNSUBSCRIBE":
                                self._subscribed = False
                            elif typ == "INTERACT_RESPONSE":
                                request_id = _as_str(msg.get("requestId") or msg.get("request_id"))
                                if not request_id:
                                    continue
                                # Allow either "content" or "text" as the response payload.
                                response = msg.get("content")
                                if response is None:
                                    response = msg.get("text")
                                with self._lock:
                                    pending = self._pending_interactions.get(request_id)
                                    if pending is not None:
                                        pending.response = response
                                        pending.event.set()

                        time.sleep(0.02)
                finally:
                    try:
                        ws_send_close(sock)
                    except Exception:
                        pass
                    try:
                        sock.close()
                    except Exception:
                        pass
                    with self._lock:
                        self._connected = False
                        self._subscribed = False

            except Exception:
                with self._lock:
                    self._connected = False
                    self._subscribed = False
                time.sleep(reconnect_delay)
                reconnect_delay = min(2.0, reconnect_delay * 1.6)


_RUNTIME_SINGLETON: VisualizerRuntime | None = None


def get_visualizer_runtime() -> VisualizerRuntime | None:
    """Return (and lazily create) the process-global VisualizerRuntime singleton.

    The runtime is enabled when `MASFACTORY_VISUALIZER_PORT` is set. Host and mode are read
    from environment variables. When unavailable, this returns None.
    """
    global _RUNTIME_SINGLETON
    if not VISUALIZER_ENABLED:
        return None
    if _RUNTIME_SINGLETON is not None:
        return _RUNTIME_SINGLETON

    host = os.environ.get("MASFACTORY_VISUALIZER_HOST") or "127.0.0.1"
    port = _as_int(os.environ.get("MASFACTORY_VISUALIZER_PORT"))
    if port is None:
        return None
    mode = _as_str(os.environ.get("MASFACTORY_VISUALIZER_MODE"))
    if not mode:
        # Best-effort: if we're running under VS Code Python debugging (debugpy),
        # treat this as debug mode even when env injection is unavailable.
        try:
            import sys

            trace = sys.gettrace()
            mod = getattr(trace, "__module__", "") if trace is not None else ""
            if trace is not None and isinstance(mod, str):
                lowered = mod.lower()
                if "debugpy" in lowered or "pydevd" in lowered or "ptvsd" in lowered:
                    mode = "debug"
        except Exception:
            mode = None
    mode = mode or "run"
    _RUNTIME_SINGLETON = VisualizerRuntime(host=host, port=port, mode=mode)
    return _RUNTIME_SINGLETON
