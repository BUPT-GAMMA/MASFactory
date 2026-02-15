from __future__ import annotations

from dataclasses import dataclass
import inspect
import os
from typing import Any


def _keys_semantics(value: object) -> dict[str, str] | None | str | None:
    # Align to MASFactory Visualizer static parser semantics:
    # - None -> null (inherit all keys)
    # - {}   -> "empty" (explicitly no keys)
    # - {..} -> dict
    if value is None:
        return None
    if isinstance(value, dict):
        if len(value) == 0:
            return "empty"
        # keep as-is (usually key->description)
        return {str(k): "" if v is None else str(v) for k, v in value.items()}
    return None


def _safe_obj(value: object) -> object:
    # Best-effort JSON-friendly conversion.
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _safe_obj(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_obj(v) for v in value]
    return str(value)


@dataclass
class SerializedGraph:
    """Serialized graph payload returned by `serialize_root_graph()`."""

    graph: dict[str, object]


def serialize_root_graph(root) -> SerializedGraph:
    """
    Serialize an in-memory MASFactory RootGraph into the same *shape* used by MASFactory
    Visualizer's
    static parser output (GraphData-ish):

    - nodes/nodeTypes/edges/subgraphs/subgraphTypes/subgraphParents
    - nodePullKeys/nodePushKeys/nodeAttributes
    - nodeInputKeys/nodeOutputKeys (from edges)
    - nodeInstructions/nodePromptTemplates (Agent-only, best-effort)
    """

    # Lazy imports to avoid circular deps at import time.
    from masfactory.components.graphs.base_graph import BaseGraph
    from masfactory.components.graphs.graph import Graph
    from masfactory.components.graphs.loop import Loop
    from masfactory.components.agents.agent import Agent

    nodes: list[str] = []
    node_types: dict[str, str] = {}
    edges: list[dict[str, object]] = []
    subgraphs: dict[str, list[str]] = {}
    subgraph_types: dict[str, str] = {}
    subgraph_parents: dict[str, str] = {}

    node_pull_keys: dict[str, object] = {}
    node_push_keys: dict[str, object] = {}
    node_attributes: dict[str, object] = {}
    node_input_keys: dict[str, object] = {}
    node_output_keys: dict[str, object] = {}
    node_instructions: dict[str, str] = {}
    node_prompt_templates: dict[str, str] = {}
    node_line_numbers: dict[str, int] = {}
    node_file_paths: dict[str, str] = {}
    node_aliases: dict[str, list[str]] = {}

    # RootGraph entry/exit should be displayed as "entry"/"exit" for UX consistency.
    root_entry = getattr(root, "_entry", None)
    root_exit = getattr(root, "_exit", None)

    def node_id(node) -> str:
        if node is root_entry:
            return "entry"
        if node is root_exit:
            return "exit"
        return getattr(node, "name", str(node))

    def node_type(node) -> str:
        nid = node_id(node)
        if nid == "entry":
            return "entry"
        if nid == "exit":
            return "exit"
        name = type(node).__name__
        # Normalize common internal nodes
        if nid.endswith("_entry"):
            return "entry"
        if nid.endswith("_exit"):
            return "exit"
        return name

    def _unwrap_callable(value: object) -> object:
        try:
            import functools

            if isinstance(value, functools.partial):
                return value.func
        except Exception:
            pass
        return value

    def _source_info(node) -> tuple[str | None, int | None]:
        """
        Best-effort source location for a node.

        Preference order:
        - CustomNode forward function (common for user code)
        - node.forward callable (if any)
        - node class definition
        """
        target: object = node.__class__
        try:
            forward = getattr(node, "_forward_function", None)
            if callable(forward):
                target = _unwrap_callable(forward)
            else:
                maybe_forward = getattr(node, "forward", None)
                if callable(maybe_forward):
                    target = _unwrap_callable(maybe_forward)
        except Exception:
            target = node.__class__

        file_path: str | None
        try:
            file_path = inspect.getsourcefile(target) or inspect.getfile(target)
        except Exception:
            file_path = None
        if file_path:
            try:
                file_path = os.path.abspath(file_path)
            except Exception:
                pass

        line: int | None
        try:
            _lines, line = inspect.getsourcelines(target)
            if not isinstance(line, int) or line <= 0:
                line = None
        except Exception:
            line = None

        return file_path, line

    def ensure_node(node, *, parent: str | None = None) -> str:
        nid = node_id(node)
        if nid not in node_types:
            nodes.append(nid)
            resolved_type = node_type(node)
            node_types[nid] = resolved_type

            # Human-friendly aliases for internal control nodes.
            if resolved_type == "entry":
                node_aliases[nid] = ["entry"]
            elif resolved_type == "exit":
                node_aliases[nid] = ["exit"]
            elif resolved_type == "Controller":
                node_aliases[nid] = ["controller"]
            elif resolved_type == "TerminateNode":
                node_aliases[nid] = ["terminate"]

            try:
                fp, ln = _source_info(node)
                if fp:
                    node_file_paths[nid] = fp
                if ln is not None:
                    node_line_numbers[nid] = ln
            except Exception:
                pass

            pull = _keys_semantics(getattr(node, "_pull_keys", None))
            push = _keys_semantics(getattr(node, "_push_keys", None))
            if pull is not None:
                node_pull_keys[nid] = pull
            if push is not None:
                node_push_keys[nid] = push

            # Prefer _default_attributes snapshot (this matches what the node actually uses).
            default_attrs = getattr(node, "_default_attributes", None)
            if isinstance(default_attrs, dict):
                node_attributes[nid] = _safe_obj(default_attrs)

            # Message keys on edges (input/output)
            try:
                in_keys = getattr(node, "input_keys", None)
                out_keys = getattr(node, "output_keys", None)
                if isinstance(in_keys, dict) and len(in_keys) > 0:
                    node_input_keys[nid] = _safe_obj(in_keys)
                if isinstance(out_keys, dict) and len(out_keys) > 0:
                    node_output_keys[nid] = _safe_obj(out_keys)
            except Exception:
                pass

            if isinstance(node, Agent):
                try:
                    ins = getattr(node, "instructions", None)
                    if isinstance(ins, str) and ins.strip():
                        node_instructions[nid] = ins
                except Exception:
                    pass
                try:
                    tmpl = getattr(node, "_prompt_template", None)
                    if isinstance(tmpl, str) and tmpl.strip():
                        node_prompt_templates[nid] = tmpl
                    elif isinstance(tmpl, list) and tmpl:
                        node_prompt_templates[nid] = "\n".join(str(x) for x in tmpl)
                except Exception:
                    pass

        if parent:
            subgraphs.setdefault(parent, [])
            if nid not in subgraphs[parent]:
                subgraphs[parent].append(nid)
            subgraph_parents[nid] = parent

        return nid

    visited_graphs: set[int] = set()

    def _iter_child_nodes(g: object) -> list[object]:
        """
        Return child node instances for a graph-like object.

        In MASFactory, graphs store children in `BaseGraph._nodes` as a dict[name -> Node].
        Older code (and some external integrations) may still treat it as a list.
        This helper normalizes both shapes.
        """
        raw = getattr(g, "_nodes", None)
        if raw is None:
            return []
        if isinstance(raw, dict):
            return list(raw.values())
        if isinstance(raw, (list, tuple, set)):
            return list(raw)
        # Best-effort: dict-like objects
        values = getattr(raw, "values", None)
        if callable(values):
            try:
                return list(values())
            except Exception:
                return []
        return []

    def walk_graph(g: BaseGraph, *, parent: str | None, is_root: bool = False) -> None:
        gid = id(g)
        if gid in visited_graphs:
            return
        visited_graphs.add(gid)

        graph_node_id = None
        if not is_root:
            graph_node_id = ensure_node(g, parent=parent)
            # Best-effort label for graph containers.
            if isinstance(g, Loop):
                subgraph_types[graph_node_id] = "Loop"
            elif isinstance(g, Graph):
                subgraph_types[graph_node_id] = "Graph"
            else:
                subgraph_types[graph_node_id] = type(g).__name__

        # Internal nodes (entry/exit or controller/terminate)
        internal_nodes: list[Any] = []
        if hasattr(g, "_entry") and hasattr(g, "_exit"):
            internal_nodes.extend([getattr(g, "_entry"), getattr(g, "_exit")])
        if isinstance(g, Loop):
            internal_nodes.extend([getattr(g, "_controller", None), getattr(g, "_terminate_node", None)])
        internal_nodes = [n for n in internal_nodes if n is not None]

        for n in internal_nodes:
            ensure_node(n, parent=graph_node_id if graph_node_id else parent)

        # Direct child nodes
        for n in _iter_child_nodes(g):
            ensure_node(n, parent=graph_node_id if graph_node_id else parent)

        # Edges inside this graph container
        for e in getattr(g, "_edges", []) or []:
            sender = getattr(e, "_sender", None)
            receiver = getattr(e, "_receiver", None)
            if sender is None or receiver is None:
                continue
            from_id = ensure_node(sender, parent=graph_node_id if graph_node_id else parent)
            to_id = ensure_node(receiver, parent=graph_node_id if graph_node_id else parent)
            keys = getattr(e, "keys", None)
            edge_obj: dict[str, object] = {"from": from_id, "to": to_id}
            if isinstance(keys, dict) and len(keys) > 0:
                edge_obj["keysDetails"] = _safe_obj(keys)
            edges.append(edge_obj)

        # Recurse into nested graphs/loops
        for n in _iter_child_nodes(g):
            if isinstance(n, BaseGraph):
                walk_graph(n, parent=graph_node_id if graph_node_id else parent, is_root=False)

    # Root: we do not render it as a graph node, but still include its entry/exit + edges.
    ensure_node(root_entry)
    ensure_node(root_exit)
    walk_graph(root, parent=None, is_root=True)

    graph_payload: dict[str, object] = {
        "nodes": nodes,
        "nodeTypes": node_types,
        "edges": edges,
        "subgraphs": subgraphs,
        "subgraphTypes": subgraph_types,
        "subgraphParents": subgraph_parents,
        "nodeLineNumbers": node_line_numbers,
        "nodeFilePaths": node_file_paths,
        "nodePullKeys": node_pull_keys,
        "nodePushKeys": node_push_keys,
        "nodeAttributes": node_attributes,
    }
    if node_aliases:
        graph_payload["nodeAliases"] = node_aliases
    if node_input_keys:
        graph_payload["nodeInputKeys"] = node_input_keys
    if node_output_keys:
        graph_payload["nodeOutputKeys"] = node_output_keys
    if node_instructions:
        graph_payload["nodeInstructions"] = node_instructions
    if node_prompt_templates:
        graph_payload["nodePromptTemplates"] = node_prompt_templates

    return SerializedGraph(graph=graph_payload)
