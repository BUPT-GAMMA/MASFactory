from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from masfactory import CustomNode, NodeTemplate


ALLOWED_NODE_TYPES = {"Action", "Switch", "Subgraph", "Loop"}
BUILTIN_NON_LOOP_IDS = {"START", "END"}
BUILTIN_LOOP_IDS = {"CONTROLLER", "TERMINATE"}
BUILTIN_IDS = BUILTIN_NON_LOOP_IDS | BUILTIN_LOOP_IDS


def _norm_node_id(node_id: str) -> str:
    return str(node_id or "").strip()


def _builtin_upper(node_id: str) -> str:
    return _norm_node_id(node_id).upper()


def _is_builtin_id(node_id: str) -> bool:
    return _builtin_upper(node_id) in BUILTIN_IDS


def _is_builtin_id_uppercase(node_id: str) -> bool:
    # Built-in IDs MUST be written in uppercase in outputs.
    nid = _norm_node_id(node_id)
    return nid in BUILTIN_IDS


@dataclass
class Edge:
    """Workflow edge definition."""

    source: str
    target: str
    condition: str | None = None


@dataclass
class Workflow:
    """Workflow graph definition (nodes + edges) parsed from model output."""

    nodes: list[dict[str, Any]]
    edges: list[Edge]


@dataclass
class ValidationResult:
    """Validation result for a workflow graph."""

    ok: bool
    issues: list[str]


_THINK_RE = re.compile(r"(?is)<\s*think\s*>.*?<\s*/\s*think\s*>")


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", str(text or "")).strip()


def _extract_code_block(text: str, lang: str) -> str | None:
    m = re.search(rf"```{re.escape(lang)}\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return str(m.group(1) or "").strip()


def _parse_role_names(role_list: str) -> set[str]:
    names: set[str] = set()
    for raw in str(role_list or "").splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        line = line.lstrip("-").strip()
        if ":" not in line:
            continue
        name = line.split(":", 1)[0].strip()
        if name:
            names.add(name)
    return names


def _load_workflow_from_output(text: str) -> tuple[Workflow | None, str]:
    cleaned = _strip_think(text)
    raw = _extract_code_block(cleaned, "json")
    if raw is None:
        m = re.search(r"(?s)\{.*\}", cleaned)
        raw = m.group(0).strip() if m else ""
    if not raw:
        return None, "no_json_found"

    try:
        obj = json.loads(raw)
    except Exception as e:
        return None, f"json_load_error:{type(e).__name__}:{e}"

    if not isinstance(obj, dict):
        return None, "json_schema_error:root_not_object"
    graph = obj.get("graph")
    if not isinstance(graph, dict):
        return None, "json_schema_error:missing_graph_object"
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return None, "json_schema_error:graph_nodes_edges_not_lists"

    wf_edges: list[Edge] = []
    for e in edges:
        if not isinstance(e, dict):
            wf_edges.append(Edge(source="", target="", condition=None))
            continue
        wf_edges.append(
            Edge(
                source=str(e.get("source") or ""),
                target=str(e.get("target") or ""),
                condition=(str(e.get("condition")) if e.get("condition") is not None else None),
            )
        )
    # Keep nodes as-is; validator will type-check.
    return Workflow(nodes=list(nodes), edges=wf_edges), ""


def _build_internal_graph(wf: Workflow, id_seen: set[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    adj: dict[str, list[str]] = {nid: [] for nid in id_seen}
    radj: dict[str, list[str]] = {nid: [] for nid in id_seen}
    for e in wf.edges:
        if not isinstance(e, Edge):
            continue
        src = _norm_node_id(e.source)
        dst = _norm_node_id(e.target)
        if src in id_seen and dst in id_seen:
            adj[src].append(dst)
            radj[dst].append(src)
    return adj, radj


def _dfs_many(roots: list[str], a: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        for y in a.get(x, []):
            if y not in seen:
                stack.append(y)
    return seen


def validate_workflow(workflow: Workflow, available_role_names: set[str]) -> ValidationResult:
    """Validate a workflow structure and return diagnostics.

    Args:
        workflow: Parsed workflow graph (nodes + edges).
        available_role_names: Allowed agent names for Action nodes.

    Returns:
        ValidationResult with `ok=True` when no issues are detected.
    """
    issues: list[str] = []

    def validate_one(wf: Workflow, *, scope: str, context: str) -> None:
        node_ids: list[str] = []
        id_seen: set[str] = set()

        for n in wf.nodes:
            if not isinstance(n, dict):
                issues.append(f"{scope}: invalid_node_object_type:{type(n).__name__}")
                continue
            nid = _norm_node_id(n.get("id") or "")
            if not nid:
                issues.append(f"{scope}: node_missing_id")
                continue
            if _builtin_upper(nid) in BUILTIN_IDS:
                issues.append(f"{scope}: reserved_node_id:{nid}")
            node_ids.append(nid)
            if nid in id_seen:
                issues.append(f"{scope}: duplicate_node_id:{nid}")
            id_seen.add(nid)

            ntype = str(n.get("type") or "").strip()
            if ntype not in ALLOWED_NODE_TYPES:
                issues.append(f"{scope}: invalid_node_type:{nid}:{ntype}")

            if ntype == "Action":
                agent = str(n.get("agent") or "").strip()
                if not agent:
                    issues.append(f"{scope}: action_missing_agent:{nid}")
                elif agent not in available_role_names:
                    issues.append(f"{scope}: action_agent_not_in_role_pool:{nid}:{agent}")
            elif ntype in {"Switch", "Loop", "Subgraph"}:
                if n.get("agent"):
                    issues.append(f"{scope}: {ntype.lower()}_should_not_have_agent:{nid}")
            if ntype in {"Loop", "Subgraph"}:
                if "sub_graph" not in n:
                    issues.append(f"{scope}: {ntype.lower()}_missing_sub_graph:{nid}")

        # Edge endpoints exist and built-in IDs are uppercase
        for e in wf.edges:
            if not isinstance(e, Edge):
                issues.append(f"{scope}: invalid_edge_object_type:{type(e).__name__}")
                continue
            src = _norm_node_id(e.source)
            dst = _norm_node_id(e.target)
            if _is_builtin_id(src) and not _is_builtin_id_uppercase(src):
                issues.append(f"{scope}: builtin_id_not_uppercase:{src}")
            if _is_builtin_id(dst) and not _is_builtin_id_uppercase(dst):
                issues.append(f"{scope}: builtin_id_not_uppercase:{dst}")

            if src not in id_seen and not _is_builtin_id(src):
                issues.append(f"{scope}: edge_unknown_source:{src}")
            if dst not in id_seen and not _is_builtin_id(dst):
                issues.append(f"{scope}: edge_unknown_target:{dst}")

        # Built-in IDs are context-specific.
        if context == "non_loop":
            for e in wf.edges:
                if not isinstance(e, Edge):
                    continue
                src_u = _builtin_upper(e.source)
                dst_u = _builtin_upper(e.target)
                if src_u in BUILTIN_LOOP_IDS or dst_u in BUILTIN_LOOP_IDS:
                    issues.append(f"{scope}: builtin_id_not_allowed_in_non_loop:{e.source}->{e.target}")
        elif context == "loop":
            for e in wf.edges:
                if not isinstance(e, Edge):
                    continue
                src_u = _builtin_upper(e.source)
                dst_u = _builtin_upper(e.target)
                if src_u in BUILTIN_NON_LOOP_IDS or dst_u in BUILTIN_NON_LOOP_IDS:
                    issues.append(f"{scope}: builtin_id_not_allowed_in_loop:{e.source}->{e.target}")

        # Switch outgoing edges must have conditions
        out_edges: dict[str, list[Edge]] = {}
        for e in wf.edges:
            if not isinstance(e, Edge):
                continue
            out_edges.setdefault(_norm_node_id(e.source), []).append(e)
        for n in wf.nodes:
            if not isinstance(n, dict):
                continue
            nid = _norm_node_id(n.get("id") or "")
            ntype = str(n.get("type") or "").strip()
            if ntype == "Switch":
                for e in out_edges.get(nid, []):
                    if not (e.condition or "").strip():
                        issues.append(f"{scope}: switch_edge_missing_condition:{nid}->{e.target}")

        # Connectivity (only if there are declared nodes)
        if node_ids:
            adj, radj = _build_internal_graph(wf, id_seen)

            if context == "non_loop":
                start_targets = [
                    _norm_node_id(e.target)
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _builtin_upper(e.source) == "START" and _norm_node_id(e.target) in id_seen
                ]
                if not start_targets:
                    issues.append(f"{scope}: missing_START_edge")
                end_sources = [
                    _norm_node_id(e.source)
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _builtin_upper(e.target) == "END" and _norm_node_id(e.source) in id_seen
                ]
                if not end_sources:
                    issues.append(f"{scope}: missing_END_edge")

                reach_from_start = _dfs_many(list(sorted(set(start_targets))), adj) if start_targets else set()
                if len(reach_from_start) != len(id_seen):
                    missing = sorted(list(id_seen - reach_from_start))
                    issues.append(f"{scope}: unreachable_from_START:{','.join(missing[:20])}")

                can_reach_end = _dfs_many(list(sorted(set(end_sources))), radj) if end_sources else set()
                if len(can_reach_end) != len(id_seen):
                    missing = sorted(list(id_seen - can_reach_end))
                    issues.append(f"{scope}: cannot_reach_END:{','.join(missing[:20])}")

            elif context == "loop":
                controller_targets = [
                    _norm_node_id(e.target)
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _builtin_upper(e.source) == "CONTROLLER" and _norm_node_id(e.target) in id_seen
                ]
                if not controller_targets:
                    issues.append(f"{scope}: missing_CONTROLLER_entry_edge")
                to_controller_sources = [
                    _norm_node_id(e.source)
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _builtin_upper(e.target) == "CONTROLLER" and _norm_node_id(e.source) in id_seen
                ]
                if not to_controller_sources:
                    issues.append(f"{scope}: missing_return_to_CONTROLLER")

                continue_edges = [
                    e
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _builtin_upper(e.source) == "CONTROLLER" and _builtin_upper(e.target) != "TERMINATE"
                ]
                if not continue_edges:
                    issues.append(f"{scope}: controller_missing_continue_branch")

                reach_from_controller = (
                    _dfs_many(list(sorted(set(controller_targets))), adj) if controller_targets else set()
                )
                if len(reach_from_controller) != len(id_seen):
                    missing = sorted(list(id_seen - reach_from_controller))
                    issues.append(f"{scope}: unreachable_from_CONTROLLER:{','.join(missing[:20])}")

                exit_sources = [
                    _norm_node_id(e.source)
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _norm_node_id(e.source) in id_seen and _builtin_upper(e.target) in {"CONTROLLER", "TERMINATE"}
                ]
                can_reach_exit = _dfs_many(list(sorted(set(exit_sources))), radj) if exit_sources else set()
                if len(can_reach_exit) != len(id_seen):
                    missing = sorted(list(id_seen - can_reach_exit))
                    issues.append(f"{scope}: cannot_reach_CONTROLLER_or_TERMINATE:{','.join(missing[:20])}")

        # CONTROLLER outgoing edges must NOT have conditions (loop context only).
        if context == "loop":
            for e in wf.edges:
                if not isinstance(e, Edge):
                    continue
                if _builtin_upper(e.source) != "CONTROLLER":
                    continue
                if (e.condition or "").strip():
                    issues.append(f"{scope}: controller_edge_has_condition:{e.source}->{e.target}")

        # Recurse into nested workflows with correct context.
        for n in wf.nodes:
            if not isinstance(n, dict):
                continue
            ntype = str(n.get("type") or "").strip()
            if ntype not in {"Loop", "Subgraph"}:
                continue
            sg = n.get("sub_graph")
            if not isinstance(sg, dict):
                continue
            sg_nodes = sg.get("nodes") or []
            sg_edges = sg.get("edges") or []
            child = Workflow(
                nodes=list(sg_nodes) if isinstance(sg_nodes, list) else [],
                edges=[
                    Edge(
                        source=str(e.get("source") or ""),
                        target=str(e.get("target") or ""),
                        condition=(str(e.get("condition")) if e.get("condition") is not None else None),
                    )
                    for e in (sg_edges if isinstance(sg_edges, list) else [])
                    if isinstance(e, dict)
                ],
            )
            child_ctx = "loop" if ntype == "Loop" else "non_loop"
            validate_one(child, scope=f"{scope}.{_norm_node_id(n.get('id') or '')}", context=child_ctx)

    validate_one(workflow, scope="root", context="non_loop")
    return ValidationResult(ok=not issues, issues=issues)


def _issue_to_advice(code: str, detail: str) -> tuple[str, str]:
    # Returns (message, suggestion)
    if code == "no_json_found":
        return ("No JSON object found in the output.", "Output a single ```json ...``` block after </think>.")
    if code.startswith("json_load_error"):
        return ("JSON parsing failed.", "Ensure the JSON is valid: quotes, commas, braces, and no trailing text.")
    if code.startswith("json_schema_error"):
        return (
            "JSON schema is incorrect (missing expected graph/nodes/edges structure).",
            'Use: { "graph": { "nodes": [...], "edges": [...] } }',
        )
    if code == "reserved_node_id":
        return (
            f"Built-in IDs must NOT be defined as nodes ({detail}).",
            "Remove START/END/CONTROLLER/TERMINATE from nodes; use them only in edges.",
        )
    if code == "builtin_id_not_uppercase":
        return (
            f"Built-in ID must be uppercase ({detail}).",
            "Use exactly: START, END, CONTROLLER, TERMINATE (uppercase only).",
        )
    if code == "missing_START_edge":
        return (
            "Non-loop workflow is missing START entry edge.",
            "Add at least one edge START -> <first node> in every non-loop workflow (root and Subgraph.sub_graph).",
        )
    if code == "missing_END_edge":
        return (
            "Non-loop workflow is missing END exit edge.",
            "Add at least one edge <sink node> -> END in every non-loop workflow (root and Subgraph.sub_graph).",
        )
    if code == "unreachable_from_START":
        return (
            f"Some nodes are unreachable from START ({detail}).",
            "Connect them into the main flow (add incoming edges) OR add START -> <node> edges for entry nodes.",
        )
    if code == "cannot_reach_END":
        return (
            f"Some nodes cannot reach END ({detail}).",
            "Ensure every node eventually leads to END (add missing edges, and ensure sinks have -> END).",
        )
    if code == "edge_unknown_source":
        return (
            f"Edge source is not a defined node or built-in ID ({detail}).",
            "Every edge source must be either a declared node id or a built-in id (START/END/CONTROLLER/TERMINATE).",
        )
    if code == "edge_unknown_target":
        return (
            f"Edge target is not a defined node or built-in ID ({detail}).",
            "Every edge target must be either a declared node id or a built-in id (START/END/CONTROLLER/TERMINATE).",
        )
    if code == "builtin_id_not_allowed_in_non_loop":
        return (
            f"Loop-only built-in ID used outside loop ({detail}).",
            "Only use CONTROLLER/TERMINATE inside Loop.sub_graph; outside loops use START/END only.",
        )
    if code == "builtin_id_not_allowed_in_loop":
        return (
            f"Non-loop built-in ID used inside loop ({detail}).",
            "Inside Loop.sub_graph, do NOT use START/END; use CONTROLLER (and optional TERMINATE).",
        )
    if code == "missing_CONTROLLER_entry_edge":
        return (
            "Loop.sub_graph is missing CONTROLLER entry edge.",
            "Add at least one edge CONTROLLER -> <loop step> inside Loop.sub_graph.",
        )
    if code == "missing_return_to_CONTROLLER":
        return (
            "Loop.sub_graph is missing return edge back to CONTROLLER.",
            "Add at least one edge <some step> -> CONTROLLER inside Loop.sub_graph to form a cycle.",
        )
    if code == "controller_missing_continue_branch":
        return (
            "CONTROLLER has no continue branch in Loop.sub_graph.",
            "Add at least one edge CONTROLLER -> <step> with a continue condition (target must not be TERMINATE).",
        )
    if code == "unreachable_from_CONTROLLER":
        return (
            f"Some loop nodes are unreachable from CONTROLLER ({detail}).",
            "Ensure CONTROLLER can reach every node in Loop.sub_graph by adding missing edges.",
        )
    if code == "cannot_reach_CONTROLLER_or_TERMINATE":
        return (
            f"Some loop nodes cannot reach CONTROLLER/TERMINATE ({detail}).",
            "Ensure each loop node can eventually return to CONTROLLER (or to TERMINATE if used).",
        )
    if code == "controller_edge_has_condition":
        return (
            f"CONTROLLER outgoing edge has a condition ({detail}).",
            "Remove `condition` from edges whose source is CONTROLLER.",
        )
    if code == "switch_edge_missing_condition":
        return (
            f"Switch outgoing edge missing condition ({detail}).",
            "Every outgoing edge from a Switch node must have a non-empty condition string.",
        )
    if code == "loop_missing_sub_graph":
        return (
            f"Loop node missing sub_graph ({detail}).",
            "Every Loop node must include sub_graph: {nodes:[...],edges:[...]}",
        )
    if code == "subgraph_missing_sub_graph":
        return (
            f"Subgraph node missing sub_graph ({detail}).",
            "Every Subgraph node must include sub_graph: {nodes:[...],edges:[...]}",
        )
    if code == "invalid_node_type":
        return (
            f"Invalid node type ({detail}).",
            "Node type must be one of: Action, Switch, Loop, Subgraph.",
        )
    if code == "node_missing_id":
        return (
            "A node is missing its id field.",
            "Every node must have an `id` string matching [A-Za-z0-9_-]+.",
        )
    if code == "action_missing_agent":
        return (
            f"Action node missing agent ({detail}).",
            "Every Action node must include an `agent` from the Available Role List.",
        )
    if code == "action_agent_not_in_role_pool":
        return (
            f"Action agent is not in Available Roles ({detail}).",
            "Use exactly one of the available role names (the part before ':') for Action.agent.",
        )
    if code == "invalid_node_object_type":
        return (
            f"Nodes array contains non-object items ({detail}).",
            "Ensure graph.nodes is a list of objects; each node must be a JSON object with id/type/label.",
        )
    if code == "invalid_edge_object_type":
        return (
            f"Edges array contains non-object items ({detail}).",
            "Ensure graph.edges is a list of objects; each edge must be a JSON object with source/target/(condition).",
        )
    return (
        f"Validation error: {code} ({detail})".strip(),
        "Follow the spec strictly and re-check START/END/CONTROLLER rules and connectivity.",
    )


def _build_system_advice(issues: list[str], parse_error: str) -> tuple[str, list[str]]:
    # Normalize (scope, code, detail) and convert to readable English advice.
    if parse_error:
        msg, sugg = _issue_to_advice(parse_error.split(":", 1)[0], parse_error)
        advice = f"1. {msg}\n   Suggestion: {sugg}\n"
        return advice.strip(), [parse_error.split(":", 1)[0]]

    items: list[tuple[str, str, str]] = []
    for iss in issues:
        scope = "root"
        rest = iss
        if ": " in iss:
            scope, rest = iss.split(": ", 1)
        code = rest.split(":", 1)[0].strip()
        detail = rest.split(":", 1)[1].strip() if ":" in rest else ""
        items.append((scope.strip() or "root", code, detail))

    # Dedup by (scope, code, detail-prefix)
    seen: set[tuple[str, str, str]] = set()
    uniq: list[tuple[str, str, str]] = []
    for scope, code, detail in items:
        key = (scope, code, detail)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((scope, code, detail))

    lines: list[str] = []
    codes: list[str] = []
    for i, (scope, code, detail) in enumerate(uniq, start=1):
        codes.append(code)
        msg, sugg = _issue_to_advice(code, detail if detail else scope)
        loc = f"[{scope}]" if scope else "[root]"
        lines.append(f"{i}. {loc} {msg}")
        lines.append(f"   Suggestion: {sugg}")
    return "\n".join(lines).strip(), sorted(set(codes))


def diagnose_forward(input_dict: dict[str, object]) -> dict[str, object]:
    """Diagnose a model-produced workflow graph design and emit system advice.

    Args:
        input_dict: Input payload containing `graph_design` and `role_list` fields.

    Returns:
        A dict with:
        - `system_advice`: human-readable advice and suggestions
        - `diagnose_has_issues`: whether issues were detected
    """
    graph_design = str(input_dict.get("graph_design") or "")
    role_list = str(input_dict.get("role_list") or "")
    available_roles = _parse_role_names(role_list)

    wf, parse_error = _load_workflow_from_output(graph_design)
    if wf is None:
        advice, codes = _build_system_advice([], parse_error or "no_json_found")
        return {
            # "graph_design": graph_design,
            "system_advice": advice,
            "diagnose_has_issues": True,
            # "diagnose_issue_count": 1,
            # "diagnose_codes": codes,
        }

    vr = validate_workflow(wf, available_role_names=available_roles)
    advice, codes = _build_system_advice(vr.issues, "")
    has_issues = not vr.ok
    if not has_issues:
        advice = "No issues detected."
    return {
        # "graph_design": graph_design,
        "system_advice": advice,
        "diagnose_has_issues": has_issues,
        # "diagnose_issue_count": int(len(vr.issues)),
        # "diagnose_codes": codes,
    }


DiagnoseNode = NodeTemplate(
    CustomNode,
    forward=diagnose_forward,
)


__all__ = [
    "DiagnoseNode",
]
