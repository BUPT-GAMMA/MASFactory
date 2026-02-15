from __future__ import annotations

import json
from typing import Any, Callable, Protocol

_VISUALIZER_STATE_ATTR = "_visualizer_runtime_hook_state"
_VISUALIZER_HANDLER_KEY = "_visualizer_runtime_hook_handler"


class _VisualizerRuntimeLike(Protocol):
    """Minimal protocol implemented by Visualizer runtime backends."""

    def node_start(self, node: object, inputs: dict[str, object]) -> object | None: ...

    def node_end(self, ctx: object | None, outputs: dict[str, object], *, node: object | None = None) -> None: ...

    def node_error(self, ctx: object | None, err: BaseException) -> None: ...

    def flow_edge_send(
        self,
        sender: object,
        receiver: object,
        *,
        edge_keys: dict[str, object] | None = None,
        message: dict[str, object] | None = None,
    ) -> None: ...

    def flow_attr_pull(
        self,
        node: object,
        *,
        scope: str | None = None,
        keys: list[str] | None = None,
        values: dict[str, object] | None = None,
        total_keys: int | None = None,
        truncated: bool = False,
    ) -> None: ...

    def flow_attr_push(
        self,
        node: object,
        *,
        scope: str | None = None,
        changes: dict[str, object] | None = None,
        total_keys: int | None = None,
        truncated: bool = False,
    ) -> None: ...

    def log(self, level: str, message: str) -> None: ...


def _is_internal_control_node(node: object) -> bool:
    name = node.name
    if name in ("entry", "exit"):
        return True
    return name.endswith(("_entry", "_exit", "_controller", "_terminate"))


class _Preview:
    """Small helper for snapshotting values with truncation for UI/history."""

    def __init__(self) -> None:
        self._missing = object()

    @property
    def missing(self) -> object:
        return self._missing

    def to_text(self, value: object, *, max_len: int = 1200) -> str:
        if value is self._missing:
            return "<missing>"
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
        if len(text) <= max_len:
            return text
        return text[:max_len] + "…(truncated)"


class _VisualizerHooks:
    """
    MASFactory Visualizer runtime hooks (installed via `hook_register(recursion=True)`).

    Key design points:
    - No manual graph traversal here: we rely on `BaseGraph.hook_register(recursion=True)`.
    - Runtime can change: callbacks read `self.runtime` dynamically.
    """

    def __init__(self) -> None:
        self.runtime: _VisualizerRuntimeLike | None = None
        self.BaseGraph: type | None = None

        # Per-run transient state.
        self._ctx_by_node_id: dict[int, list[object]] = {}
        self._exec_ctx_by_node_id: dict[int, list[dict[str, Any]]] = {}
        self._env_name_by_id: dict[int, str] = {}

        self._preview = _Preview()

        # Stable callback identities used for registration.
        self.cb_before_forward = self.before_forward
        self.cb_after_forward = self.after_forward
        self.cb_error_forward = self.error_forward
        self.cb_after_build = self.after_build
        self.cb_before_execute = self.before_execute
        self.cb_after_execute = self.after_execute
        self.cb_edge_send = self.edge_send

    def reset_run_state(self) -> None:
        self._ctx_by_node_id.clear()
        self._exec_ctx_by_node_id.clear()
        self._env_name_by_id.clear()

    def before_forward(self, node, input_dict, *args, **kwargs) -> None:
        runtime = self.runtime
        if runtime is None:
            return
        try:
            ctx = runtime.node_start(node, input_dict)
        except Exception:
            return
        if ctx is None:
            return
        self._ctx_by_node_id.setdefault(id(node), []).append(ctx)

    def after_forward(self, node, result, input_dict, *args, **kwargs) -> None:
        runtime = self.runtime
        if runtime is None:
            return
        stack = self._ctx_by_node_id.get(id(node))
        if not stack:
            return
        ctx = stack.pop()
        if not stack:
            self._ctx_by_node_id.pop(id(node), None)
        output_dict = result if isinstance(result, dict) else {"output": result}
        try:
            runtime.node_end(ctx, output_dict, node=node)
        except Exception:
            return

    def error_forward(self, node, err, input_dict, *args, **kwargs) -> None:
        runtime = self.runtime
        if runtime is None:
            return
        stack = self._ctx_by_node_id.get(id(node))
        ctx = stack.pop() if stack else None
        if stack is not None and len(stack) == 0:
            self._ctx_by_node_id.pop(id(node), None)
        try:
            runtime.node_error(ctx, err)
        except Exception:
            return

    def after_build(self, node, result, *args, **kwargs) -> None:
        runtime = self.runtime
        if runtime is None:
            return
        try:
            name = node.name
            typ = type(node).__name__
            env = node.attributes
            attr_count = len(env)
            runtime.log("info", f"[build] node={name} type={typ} defaultAttrs={attr_count}")
        except Exception:
            return

    def before_execute(self, node, outer_env, *args, **kwargs) -> None:
        """Hook: before Node.execute().

        Tracks attribute pulls and snapshots candidate push keys so `after_execute()` can compute
        and report attribute changes as a flow event.
        """
        runtime = self.runtime
        base_graph_cls = self.BaseGraph
        if runtime is None or base_graph_cls is None:
            return
        try:
            # Keep attribute-scope names for child events.
            if isinstance(node, base_graph_cls):
                env = node.attributes
                self._env_name_by_id[id(env)] = node.name
                return

            if _is_internal_control_node(node):
                return

            scope = self._env_name_by_id.get(id(outer_env))

            pull_keys = node.pull_keys
            pulled_keys: list[str] = []
            pulled_values: dict[str, object] = {}
            total_pull: int | None = None
            truncated_pull = False

            if pull_keys is None:
                all_keys = list(outer_env.keys())
                total_pull = len(all_keys)
                pulled_keys = all_keys[:60]
                truncated_pull = total_pull > len(pulled_keys)
                pulled_values = {k: outer_env.get(k) for k in pulled_keys}
            elif pull_keys:
                pulled_keys = [str(k) for k in pull_keys.keys()]
                total_pull = len(pulled_keys)
                pulled_values = {k: outer_env.get(k) for k in pulled_keys if k in outer_env}

            if pulled_keys:
                runtime.flow_attr_pull(
                    node,
                    scope=scope,
                    keys=pulled_keys,
                    values=pulled_values,
                    total_keys=total_pull,
                    truncated=truncated_pull,
                )

            push_keys = node.push_keys
            candidate_keys: list[str] = []
            if push_keys:
                candidate_keys = [str(k) for k in push_keys.keys()]
            elif push_keys is None:
                if pull_keys:
                    candidate_keys = [str(k) for k in pull_keys.keys()]
                elif pull_keys is None:
                    candidate_keys = [str(k) for k in outer_env.keys()]

            if not candidate_keys:
                return

            total_push = len(candidate_keys)
            sample_keys = candidate_keys[:120]
            truncated_push = total_push > len(sample_keys)
            snapshot = {k: self._preview.to_text(outer_env.get(k, self._preview.missing)) for k in sample_keys}
            self._exec_ctx_by_node_id.setdefault(id(node), []).append(
                {
                    "scope": scope,
                    "keys": sample_keys,
                    "total": total_push,
                    "truncated": bool(truncated_push),
                    "snapshot": snapshot,
                }
            )
        except Exception:
            return

    def after_execute(self, node, result, outer_env, *args, **kwargs) -> None:
        """Hook: after Node.execute().

        Computes attribute changes relative to the snapshot captured by `before_execute()` and
        reports them as an attribute-push flow event.
        """
        runtime = self.runtime
        base_graph_cls = self.BaseGraph
        if runtime is None or base_graph_cls is None:
            return
        try:
            if isinstance(node, base_graph_cls):
                return
            if _is_internal_control_node(node):
                return

            stack = self._exec_ctx_by_node_id.get(id(node))
            if not stack:
                return
            ctx = stack.pop()
            if not stack:
                self._exec_ctx_by_node_id.pop(id(node), None)

            keys: list[str] = ctx.get("keys") or []
            snapshot: dict[str, str] = ctx.get("snapshot") or {}
            scope: str | None = ctx.get("scope")
            total: int | None = ctx.get("total")
            truncated: bool = bool(ctx.get("truncated"))

            changes: dict[str, object] = {}
            for k in keys:
                before = snapshot.get(k, "<missing>")
                after_v = outer_env.get(k, self._preview.missing)
                after = self._preview.to_text(after_v)
                if after != before:
                    changes[k] = outer_env.get(k)

            if not changes:
                return
            runtime.flow_attr_push(node, scope=scope, changes=changes, total_keys=total, truncated=truncated)
        except Exception:
            return

    def edge_send(self, sender, receiver, message, *args, **kwargs) -> None:
        runtime = self.runtime
        if runtime is None:
            return
        try:
            edge_obj = None
            for e in sender.out_edges:
                if e.receiver is receiver:
                    edge_obj = e
                    break
            edge_keys = edge_obj.keys if edge_obj is not None else None
            msg = (
                {k: message[k] for k in edge_keys.keys()} if edge_keys is not None else {}
            )
            runtime.flow_edge_send(sender, receiver, edge_keys=edge_keys, message=msg)
        except Exception:
            return

    def install(self, root_graph: object) -> None:
        """
        Register hooks using `BaseGraph.hook_register(recursion=True)`.
        """
        try:
            from masfactory.core.node import Node
            from masfactory.core.edge import Edge
        except Exception:
            return

        def _exclude_root(obj: object) -> bool:
            return obj is not root_graph

        # Exclude root graph itself from node events.
        root_graph.hook_register(
            Node.Hook.FORWARD.BEFORE,
            self.cb_before_forward,
            recursion=True,
            target_type=Node,
            target_filter=_exclude_root,
        )
        root_graph.hook_register(
            Node.Hook.FORWARD.AFTER,
            self.cb_after_forward,
            recursion=True,
            target_type=Node,
            target_filter=_exclude_root,
        )
        root_graph.hook_register(
            Node.Hook.FORWARD.ERROR,
            self.cb_error_forward,
            recursion=True,
            target_type=Node,
            target_filter=_exclude_root,
        )

        # Include BaseGraph nodes for environment scope mapping.
        root_graph.hook_register(
            Node.Hook.EXECUTE.BEFORE,
            self.cb_before_execute,
            recursion=True,
            target_type=Node,
        )
        root_graph.hook_register(
            Node.Hook.EXECUTE.AFTER,
            self.cb_after_execute,
            recursion=True,
            target_type=Node,
        )

        root_graph.hook_register(
            Node.Hook.BUILD.AFTER,
            self.cb_after_build,
            recursion=True,
            target_type=Node,
            target_filter=_exclude_root,
        )

        # Edge flow: use edge hooks (captures internal node flows too).
        root_graph.hook_register(
            Edge.Hook.SEND_MESSAGE,
            self.cb_edge_send,
            recursion=True,
            target_type=Edge,
        )


def install_root_graph_runtime_hooks(root_graph: object, runtime: object) -> None:
    """
    Attach Visualizer runtime hooks to a built RootGraph (registers callbacks once).
    """
    try:
        from masfactory.components.graphs.base_graph import BaseGraph
    except Exception:
        return

    state = getattr(root_graph, _VISUALIZER_STATE_ATTR, None)
    if not isinstance(state, dict):
        state = {}
        setattr(root_graph, _VISUALIZER_STATE_ATTR, state)

    handler = state.get(_VISUALIZER_HANDLER_KEY)
    if not isinstance(handler, _VisualizerHooks):
        handler = _VisualizerHooks()
        state[_VISUALIZER_HANDLER_KEY] = handler

    handler.runtime = runtime  # type: ignore[assignment]
    handler.BaseGraph = BaseGraph  # type: ignore[assignment]
    handler.reset_run_state()
    try:
        handler.install(root_graph)
    except Exception:
        return


def reset_root_graph_runtime_hooks(root_graph: object, runtime: object) -> None:
    """
    Prepare hooks for a new run without re-registering callbacks.

    - Updates runtime handle (so hook callbacks use the latest bridge wrapper)
    - Clears per-run transient state (ctx stacks, env-name maps, etc.)
    """
    try:
        from masfactory.components.graphs.base_graph import BaseGraph
    except Exception:
        return

    state = getattr(root_graph, _VISUALIZER_STATE_ATTR, None)
    if not isinstance(state, dict):
        return
    handler = state.get(_VISUALIZER_HANDLER_KEY)
    if not isinstance(handler, _VisualizerHooks):
        return

    handler.runtime = runtime  # type: ignore[assignment]
    handler.BaseGraph = BaseGraph  # type: ignore[assignment]
    handler.reset_run_state()
