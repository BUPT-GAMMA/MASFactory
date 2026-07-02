from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

from masfactory.aml import parse_aml_document
from masfactory import CustomNode, NodeTemplate


ALLOWED_NODE_TYPES = {"agent", "logic_switch", "agent_switch", "custom_node", "graph", "loop"}
BUILTIN_NON_LOOP_IDS = {"entry", "exit"}
BUILTIN_LOOP_IDS = {"controller", "terminate"}
BUILTIN_IDS = BUILTIN_NON_LOOP_IDS | BUILTIN_LOOP_IDS
LEGACY_ENDPOINT_IDS = {"START", "END", "CONTROLLER", "TERMINATE"}
NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _norm_node_id(node_id: str) -> str:
    return str(node_id or "").strip()


def _builtin_norm(node_id: str) -> str:
    return _norm_node_id(node_id).lower()


def _is_builtin_id(node_id: str) -> bool:
    return _builtin_norm(node_id) in BUILTIN_IDS


def _is_builtin_id_exact(node_id: str) -> bool:
    # AML built-in endpoints are lowercase.
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
    graph_refs: set[str] | None = None


@dataclass
class ValidationResult:
    """Validation result for a workflow graph."""

    ok: bool
    issues: list[str]


_THINK_RE = re.compile(r"(?is)<\s*think\s*>.*?<\s*/\s*think\s*>")


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", str(text or "")).strip()


def _extract_aml_document(text: str) -> str | None:
    clean = _strip_think(text)
    xml_block = _extract_code_block(clean, "xml")
    if xml_block:
        clean = xml_block
    start = clean.find("<aml")
    if start < 0:
        return None
    end_marker = "</aml>"
    end = clean.rfind(end_marker)
    return clean[start : end + len(end_marker)].strip() if end >= start else clean[start:].strip()


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _direct_children(parent: ET.Element, name: str | None = None) -> list[ET.Element]:
    children = list(parent)
    if name is None:
        return children
    return [child for child in children if _local_name(child.tag) == name]


def _first_direct(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _local_name(child.tag) == name:
            return child
    return None


def _ref_id(value: object) -> str:
    ref = str(value or "").strip()
    return ref[1:] if ref.startswith("#") else ref


def _agent_definition_ids(root: ET.Element) -> set[str]:
    ids: set[str] = set()
    for agents in root.iter():
        if _local_name(agents.tag) != "agents":
            continue
        for agent in _direct_children(agents, "agent"):
            agent_id = str(agent.attrib.get("id") or "").strip()
            if agent_id:
                ids.add(agent_id)
    return ids


def _find_root_graph(root: ET.Element) -> ET.Element | None:
    graphs = [element for element in root.iter() if _local_name(element.tag) == "graph"]
    for graph in graphs:
        if str(graph.attrib.get("kind") or "").strip() == "root":
            return graph
    return graphs[0] if graphs else None


def _edge_from_element(edge: ET.Element) -> Edge:
    condition = str(edge.attrib.get("if") or edge.attrib.get("match") or "").strip() or None
    return Edge(
        source=str(edge.attrib.get("from") or "").strip(),
        target=str(edge.attrib.get("to") or "").strip(),
        condition=condition,
    )


def _parse_graph_scope(
    graph: ET.Element,
    *,
    agent_defs: set[str],
    graph_refs: set[str],
) -> Workflow:
    nodes: list[dict[str, Any]] = []
    edges: list[Edge] = []

    nodes_el = _first_direct(graph, "nodes")
    if nodes_el is not None:
        for child in _direct_children(nodes_el):
            tag = _local_name(child.tag)
            if tag not in ALLOWED_NODE_TYPES:
                nodes.append({"id": str(child.attrib.get("id") or "").strip(), "type": tag})
                continue

            node_id = str(child.attrib.get("id") or child.attrib.get("name") or "").strip()
            node: dict[str, Any] = {
                "id": node_id,
                "type": tag,
            }
            if tag == "agent":
                node["ref"] = _ref_id(child.attrib.get("ref"))
                node["ref_defined"] = bool(node["ref"] and node["ref"] in agent_defs)
            elif tag == "loop":
                node["has_terminate"] = _first_direct(child, "terminate") is not None
                if _first_direct(child, "nodes") is not None or _first_direct(child, "edges") is not None:
                    node["sub_graph"] = _parse_graph_scope(child, agent_defs=agent_defs, graph_refs=graph_refs)
            elif tag == "graph":
                ref = _ref_id(child.attrib.get("ref"))
                implementation = str(child.attrib.get("implementation") or "").strip()
                if ref:
                    node["ref"] = ref
                if implementation:
                    node["implementation"] = implementation
                graph_refs.add(ref.split("::", 1)[-1] if ref else node_id)
                if _first_direct(child, "nodes") is not None or _first_direct(child, "edges") is not None:
                    node["sub_graph"] = _parse_graph_scope(child, agent_defs=agent_defs, graph_refs=graph_refs)
            nodes.append(node)

    edges_el = _first_direct(graph, "edges")
    if edges_el is not None:
        for edge in _direct_children(edges_el, "edge"):
            edges.append(_edge_from_element(edge))

    return Workflow(nodes=nodes, edges=edges, graph_refs=graph_refs)


def _load_workflow_from_aml(text: str) -> tuple[Workflow | None, str]:
    aml = _extract_aml_document(text)
    if not aml:
        return None, "aml_missing_document"
    try:
        parse_aml_document(aml, strict=True)
    except Exception as exc:
        detail = str(exc).replace("\n", " ").strip()
        return None, f"aml_parse_error:{detail}"
    try:
        root = ET.fromstring(aml)
    except Exception as exc:
        detail = str(exc).replace("\n", " ").strip()
        return None, f"aml_parse_error:{detail}"
    if _local_name(root.tag) != "aml":
        return None, "aml_missing_document"
    graph = _find_root_graph(root)
    if graph is None:
        return None, "aml_missing_root_graph"
    graph_refs: set[str] = set()
    workflow = _parse_graph_scope(graph, agent_defs=_agent_definition_ids(root), graph_refs=graph_refs)
    return workflow, ""


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
        available_role_names: Available role names supplied to the planner. The AML planner uses
            role-derived agent definition ids, so this set is advisory and not treated as an exact id list.

    Returns:
        ValidationResult with `ok=True` when no issues are detected.
    """
    issues: list[str] = []

    def validate_one(wf: Workflow, *, scope: str, context: str) -> None:
        node_ids: list[str] = []
        id_seen: set[str] = set()
        graph_refs = wf.graph_refs or set()

        for n in wf.nodes:
            if not isinstance(n, dict):
                issues.append(f"{scope}: invalid_node_object_type:{type(n).__name__}")
                continue
            nid = _norm_node_id(n.get("id") or "")
            if not nid:
                issues.append(f"{scope}: node_missing_id")
                continue
            if _builtin_norm(nid) in BUILTIN_IDS:
                issues.append(f"{scope}: reserved_node_id:{nid}")
            if not NODE_ID_PATTERN.match(nid):
                issues.append(f"{scope}: invalid_node_id:{nid}")
            node_ids.append(nid)
            if nid in id_seen:
                issues.append(f"{scope}: duplicate_node_id:{nid}")
            id_seen.add(nid)

            ntype = str(n.get("type") or "").strip()
            if ntype not in ALLOWED_NODE_TYPES:
                issues.append(f"{scope}: invalid_node_type:{nid}:{ntype}")

            if ntype == "agent":
                ref = str(n.get("ref") or "").strip()
                if not ref:
                    issues.append(f"{scope}: agent_missing_ref:{nid}")
                elif not n.get("ref_defined"):
                    issues.append(f"{scope}: agent_ref_not_defined:{nid}:{ref}")
            elif ntype == "loop":
                if "sub_graph" not in n:
                    issues.append(f"{scope}: loop_missing_body:{nid}")
                if not n.get("has_terminate"):
                    issues.append(f"{scope}: loop_missing_terminate:{nid}")
            elif ntype == "graph":
                has_external_target = bool(str(n.get("ref") or "").strip() or str(n.get("implementation") or "").strip())
                if "sub_graph" not in n and not has_external_target:
                    issues.append(f"{scope}: graph_missing_body:{nid}")

        # Edge endpoints exist and built-in endpoints are lowercase.
        for e in wf.edges:
            if not isinstance(e, Edge):
                issues.append(f"{scope}: invalid_edge_object_type:{type(e).__name__}")
                continue
            src = _norm_node_id(e.source)
            dst = _norm_node_id(e.target)
            if not src or not dst:
                issues.append(f"{scope}: edge_missing_endpoint:{src}->{dst}")
                continue
            if src in LEGACY_ENDPOINT_IDS or dst in LEGACY_ENDPOINT_IDS:
                issues.append(f"{scope}: legacy_endpoint_name:{src}->{dst}")
            if _is_builtin_id(src) and not _is_builtin_id_exact(src):
                issues.append(f"{scope}: builtin_id_not_lowercase:{src}")
            if _is_builtin_id(dst) and not _is_builtin_id_exact(dst):
                issues.append(f"{scope}: builtin_id_not_lowercase:{dst}")

            if src not in id_seen and src not in graph_refs and not _is_builtin_id(src):
                issues.append(f"{scope}: edge_unknown_source:{src}")
            if dst not in id_seen and dst not in graph_refs and not _is_builtin_id(dst):
                issues.append(f"{scope}: edge_unknown_target:{dst}")

        # Built-in IDs are context-specific.
        if context == "non_loop":
            for e in wf.edges:
                if not isinstance(e, Edge):
                    continue
                src_b = _builtin_norm(e.source)
                dst_b = _builtin_norm(e.target)
                if src_b in BUILTIN_LOOP_IDS or dst_b in BUILTIN_LOOP_IDS:
                    issues.append(f"{scope}: builtin_id_not_allowed_in_non_loop:{e.source}->{e.target}")
        elif context == "loop":
            for e in wf.edges:
                if not isinstance(e, Edge):
                    continue
                src_b = _builtin_norm(e.source)
                dst_b = _builtin_norm(e.target)
                if src_b in BUILTIN_NON_LOOP_IDS or dst_b in BUILTIN_NON_LOOP_IDS:
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
            if ntype in {"logic_switch", "agent_switch"}:
                for e in out_edges.get(nid, []):
                    if not (e.condition or "").strip():
                        issues.append(f"{scope}: switch_edge_missing_condition:{nid}->{e.target}")

        # Connectivity (only if there are declared nodes)
        if node_ids:
            adj, radj = _build_internal_graph(wf, id_seen)

            if context == "non_loop":
                entry_targets = [
                    _norm_node_id(e.target)
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _builtin_norm(e.source) == "entry" and _norm_node_id(e.target) in id_seen
                ]
                if not entry_targets:
                    issues.append(f"{scope}: missing_entry_edge")
                exit_sources = [
                    _norm_node_id(e.source)
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _builtin_norm(e.target) == "exit" and _norm_node_id(e.source) in id_seen
                ]
                if not exit_sources:
                    issues.append(f"{scope}: missing_exit_edge")

                reach_from_entry = _dfs_many(list(sorted(set(entry_targets))), adj) if entry_targets else set()
                if len(reach_from_entry) != len(id_seen):
                    missing = sorted(list(id_seen - reach_from_entry))
                    issues.append(f"{scope}: unreachable_from_entry:{','.join(missing[:20])}")

                can_reach_exit = _dfs_many(list(sorted(set(exit_sources))), radj) if exit_sources else set()
                if len(can_reach_exit) != len(id_seen):
                    missing = sorted(list(id_seen - can_reach_exit))
                    issues.append(f"{scope}: cannot_reach_exit:{','.join(missing[:20])}")

            elif context == "loop":
                controller_targets = [
                    _norm_node_id(e.target)
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _builtin_norm(e.source) == "controller" and _norm_node_id(e.target) in id_seen
                ]
                if not controller_targets:
                    issues.append(f"{scope}: missing_controller_entry_edge")
                to_controller_sources = [
                    _norm_node_id(e.source)
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _builtin_norm(e.target) == "controller" and _norm_node_id(e.source) in id_seen
                ]
                if not to_controller_sources:
                    issues.append(f"{scope}: missing_return_to_controller")

                continue_edges = [
                    e
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _builtin_norm(e.source) == "controller" and _builtin_norm(e.target) != "terminate"
                ]
                if not continue_edges:
                    issues.append(f"{scope}: controller_missing_continue_branch")

                reach_from_controller = (
                    _dfs_many(list(sorted(set(controller_targets))), adj) if controller_targets else set()
                )
                if len(reach_from_controller) != len(id_seen):
                    missing = sorted(list(id_seen - reach_from_controller))
                    issues.append(f"{scope}: unreachable_from_controller:{','.join(missing[:20])}")

                exit_sources = [
                    _norm_node_id(e.source)
                    for e in wf.edges
                    if isinstance(e, Edge)
                    if _norm_node_id(e.source) in id_seen and _builtin_norm(e.target) in {"controller", "terminate"}
                ]
                can_reach_exit = _dfs_many(list(sorted(set(exit_sources))), radj) if exit_sources else set()
                if len(can_reach_exit) != len(id_seen):
                    missing = sorted(list(id_seen - can_reach_exit))
                    issues.append(f"{scope}: cannot_reach_controller_or_terminate:{','.join(missing[:20])}")

        # controller outgoing edges must not have conditions; loop exit logic lives on <terminate>.
        if context == "loop":
            for e in wf.edges:
                if not isinstance(e, Edge):
                    continue
                if _builtin_norm(e.source) != "controller":
                    continue
                if (e.condition or "").strip():
                    issues.append(f"{scope}: controller_edge_has_condition:{e.source}->{e.target}")

        # Recurse into nested workflows with correct context.
        for n in wf.nodes:
            if not isinstance(n, dict):
                continue
            ntype = str(n.get("type") or "").strip()
            if ntype not in {"loop", "graph"}:
                continue
            sg = n.get("sub_graph")
            if not isinstance(sg, Workflow):
                continue
            child_ctx = "loop" if ntype == "loop" else "non_loop"
            validate_one(sg, scope=f"{scope}.{_norm_node_id(n.get('id') or '')}", context=child_ctx)

    validate_one(workflow, scope="root", context="non_loop")
    return ValidationResult(ok=not issues, issues=issues)


def _issue_to_advice(code: str, detail: str) -> tuple[str, str]:
    # Returns (message, suggestion)
    if code == "aml_missing_document":
        return (
            "No AML document found in the output.",
            "Output one complete AML v0.2 XML document starting with <aml ...> and ending with </aml>.",
        )
    if code == "aml_missing_root_graph":
        return (
            "AML does not contain a workflow graph.",
            'Add a root graph under definitions, for example <graph id="root" kind="root">.',
        )
    if code.startswith("aml_parse_error"):
        return (
            "AML parsing or validation failed.",
            "Fix XML, node ids, required agent references, and endpoint names; use entry/exit outside loops and controller/terminate inside loops.",
        )
    if code == "reserved_node_id":
        return (
            f"Built-in endpoints must not be defined as nodes ({detail}).",
            "Remove entry/exit/controller/terminate from <nodes>; use them only as edge endpoints.",
        )
    if code == "invalid_node_id":
        return (
            f"Node id is invalid ({detail}).",
            "Use ids matching [A-Za-z0-9_-]+.",
        )
    if code == "builtin_id_not_lowercase":
        return (
            f"Built-in endpoint must be lowercase ({detail}).",
            "Use exactly: entry, exit, controller, terminate.",
        )
    if code == "edge_missing_endpoint":
        return (
            f"An edge is missing from/to ({detail}).",
            'Every AML edge must use non-empty from="..." and to="..." attributes.',
        )
    if code == "legacy_endpoint_name":
        return (
            f"Edge uses legacy endpoint names ({detail}).",
            "Use AML endpoint names: entry/exit in non-loop graphs and controller/terminate inside loops.",
        )
    if code == "missing_entry_edge":
        return (
            "Non-loop graph is missing an entry edge.",
            "Add at least one edge from entry to the first node in every root or nested non-loop graph.",
        )
    if code == "missing_exit_edge":
        return (
            "Non-loop graph is missing an exit edge.",
            "Add at least one edge from a sink node to exit in every root or nested non-loop graph.",
        )
    if code == "unreachable_from_entry":
        return (
            f"Some nodes are unreachable from entry ({detail}).",
            "Connect them into the main flow or add entry edges for valid entry nodes.",
        )
    if code == "cannot_reach_exit":
        return (
            f"Some nodes cannot reach exit ({detail}).",
            "Ensure every node eventually leads to exit.",
        )
    if code == "edge_unknown_source":
        return (
            f"Edge source is not a defined node or endpoint ({detail}).",
            "Every edge source must be a node id or one of entry/exit/controller/terminate allowed in that scope.",
        )
    if code == "edge_unknown_target":
        return (
            f"Edge target is not a defined node or endpoint ({detail}).",
            "Every edge target must be a node id or one of entry/exit/controller/terminate allowed in that scope.",
        )
    if code == "builtin_id_not_allowed_in_non_loop":
        return (
            f"Loop-only endpoint used outside a loop ({detail}).",
            "Use controller/terminate only inside <loop>; non-loop graphs use entry/exit.",
        )
    if code == "builtin_id_not_allowed_in_loop":
        return (
            f"Non-loop endpoint used inside a loop ({detail}).",
            "Inside <loop>, use controller and optional terminate; do not use entry/exit.",
        )
    if code == "missing_controller_entry_edge":
        return (
            "Loop body is missing a controller entry edge.",
            "Add at least one edge from controller to a loop step inside the <loop> body.",
        )
    if code == "missing_return_to_controller":
        return (
            "Loop body is missing a return edge back to controller.",
            "Add at least one edge from a loop step back to controller.",
        )
    if code == "controller_missing_continue_branch":
        return (
            "controller has no continue branch in the loop body.",
            "Add at least one edge from controller to a loop step.",
        )
    if code == "unreachable_from_controller":
        return (
            f"Some loop nodes are unreachable from controller ({detail}).",
            "Ensure controller can reach every node in the loop body.",
        )
    if code == "cannot_reach_controller_or_terminate":
        return (
            f"Some loop nodes cannot reach controller/terminate ({detail}).",
            "Ensure each loop node can return to controller or reach terminate.",
        )
    if code == "controller_edge_has_condition":
        return (
            f"controller outgoing edge has a condition ({detail}).",
            "Put loop termination on <terminate .../> and leave controller outgoing edges unconditional.",
        )
    if code == "switch_edge_missing_condition":
        return (
            f"Switch outgoing edge is missing a predicate ({detail}).",
            'Every outgoing edge from <logic_switch> or <agent_switch> needs if="..." or match="...".',
        )
    if code == "loop_missing_body":
        return (
            f"Loop node is missing its body ({detail}).",
            "Every <loop> must contain nested <nodes> and <edges>.",
        )
    if code == "loop_missing_terminate":
        return (
            f"Loop node is missing <terminate> ({detail}).",
            'Add <terminate match="..."/> or <terminate if="..."/> to the loop.',
        )
    if code == "graph_missing_body":
        return (
            f"Nested graph is missing an inline body or external target ({detail}).",
            "Either add nested <nodes>/<edges> or give the <graph> a ref or implementation.",
        )
    if code == "invalid_node_type":
        return (
            f"Invalid AML node tag ({detail}).",
            "Use only <agent>, <logic_switch>, <agent_switch>, <custom_node>, <graph>, or <loop>.",
        )
    if code == "node_missing_id":
        return (
            "A node is missing its id field.",
            "Every node must have an `id` string matching [A-Za-z0-9_-]+.",
        )
    if code == "agent_missing_ref":
        return (
            f"Agent node is missing ref ({detail}).",
            'Every <agent> node must include ref="#agent_definition_id".',
        )
    if code == "agent_ref_not_defined":
        return (
            f"Agent node references an undefined agent definition ({detail}).",
            "Add the referenced id under <definitions><agents> or update the node ref.",
        )
    if code == "invalid_node_object_type":
        return (
            f"Nodes collection contains an invalid item ({detail}).",
            "Ensure every workflow node is a valid AML element.",
        )
    if code == "invalid_edge_object_type":
        return (
            f"Edges collection contains an invalid item ({detail}).",
            "Ensure every workflow edge is a valid <edge> element with from/to.",
        )
    return (
        f"Validation error: {code} ({detail})".strip(),
        "Follow the AML spec and re-check entry/exit/controller connectivity.",
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
    """Diagnose a model-produced AML workflow and emit system advice.

    Args:
        input_dict: Input payload containing `aml` and `role_list` fields.

    Returns:
        A dict with:
        - `system_advice`: human-readable advice and suggestions
        - `diagnose_has_issues`: whether issues were detected
    """
    aml = str(input_dict.get("aml") or "")
    role_list = str(input_dict.get("role_list") or "")
    available_roles = _parse_role_names(role_list)

    wf, parse_error = _load_workflow_from_aml(aml)
    if wf is None:
        advice, _codes = _build_system_advice([], parse_error or "aml_missing_document")
        return {
            "system_advice": advice,
            "diagnose_has_issues": True,
        }

    vr = validate_workflow(wf, available_role_names=available_roles)
    advice, _codes = _build_system_advice(vr.issues, "")
    has_issues = not vr.ok
    if not has_issues:
        advice = "No issues detected."
    return {
        "system_advice": advice,
        "diagnose_has_issues": has_issues,
    }


DiagnoseNode = NodeTemplate(
    CustomNode,
    forward=diagnose_forward,
)


__all__ = [
    "DiagnoseNode",
]
