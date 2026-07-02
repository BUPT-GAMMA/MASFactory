from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

from masfactory.compatibility.common.blueprint import (
    ENTRY_TOKEN,
    EXIT_TOKEN,
    ExternalEdge,
    ExternalNode,
    GraphBlueprint,
)
from masfactory.compatibility.common.conditions import is_always_true_condition, needs_logic_switch
from masfactory.compatibility.common.loops import LoopPlan, nodes_in_loops, plan_loop_regions
from masfactory.compatibility.common.names import slugify_node_name, uniquify_dify_node_names, uniquify_names
from masfactory.compatibility.common.wire_loops import build_loop_aware_wire_pairs

_SWITCH_KINDS = frozenset({"if-else", "question-classifier"})
_LOOP_KINDS = frozenset({"loop", "iteration", "LoopComponent"})
_SUBGRAPH_KINDS = frozenset({"subgraph"})
_SKIP_KINDS = frozenset({"loop-start", "loop-end", "iteration-start", "custom-note", "note"})


def _is_dify_blueprint(blueprint: GraphBlueprint) -> bool:
    meta = blueprint.metadata or {}
    return isinstance(meta.get("dify"), dict)


def _dify_skip_ids(blueprint: GraphBlueprint) -> frozenset[str]:
    dify = (blueprint.metadata or {}).get("dify") or {}
    raw = dify.get("container_child_node_ids")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(str(x) for x in raw)


def _dify_loop_subgraphs(blueprint: GraphBlueprint) -> dict[str, dict[str, Any]]:
    dify = (blueprint.metadata or {}).get("dify") or {}
    raw = dify.get("loop_subgraphs")
    return dict(raw) if isinstance(raw, dict) else {}


def _build_id_map(blueprint: GraphBlueprint, *, active_nodes: list[ExternalNode]) -> dict[str, str]:
    if _is_dify_blueprint(blueprint):
        return uniquify_dify_node_names(active_nodes)
    return uniquify_names(n.id for n in active_nodes)


def _infer_aml_kind(ext: ExternalNode) -> str:
    kind = ext.kind or ""
    if kind in _SWITCH_KINDS:
        return "agent_switch"
    if kind in _SUBGRAPH_KINDS:
        return "graph"
    return "custom_node"


def _compat_node(
    ext: ExternalNode,
    *,
    node_id: str,
    scope: str,
    aml_kind: str = "custom_node",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": node_id,
        "label": ext.label or ext.kind or node_id,
        "kind": aml_kind,
        "attributes": {
            "compat_external_id": ext.id,
            "compat_kind": ext.kind,
            "compat_label": ext.label,
            "compat_scope": scope,
            "compat_raw": ext.raw,
        },
    }
    if aml_kind == "loop":
        node.setdefault("max_iterations", 20)
        node.setdefault("terminate_condition", "Imported loop (compatibility preview).")
    if extra:
        node.update(extra)
    return node


def _edge_condition(edge: ExternalEdge) -> str | None:
    raw = edge.raw if isinstance(edge.raw, dict) else {}
    for key in ("condition", "source_handle", "label"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip() and not is_always_true_condition(val):
            return val.strip()
    if edge.source_handle and not is_always_true_condition(edge.source_handle):
        return str(edge.source_handle).strip()
    return None


def _index_edges(edges: tuple[ExternalEdge, ...]) -> dict[tuple[str, str], ExternalEdge]:
    out: dict[tuple[str, str], ExternalEdge] = {}
    for edge in edges:
        out[(edge.source, edge.target)] = edge
    return out


def _wire_pairs_to_aml_edges(
    wire_pairs: list[tuple[str, str]],
    *,
    id_to_name: dict[str, str],
    route_nodes: dict[str, str] | None = None,
    edges_by_pair: dict[tuple[str, str], ExternalEdge] | None = None,
) -> list[dict[str, Any]]:
    route_nodes = route_nodes or {}
    edges_by_pair = edges_by_pair or {}
    out: list[dict[str, Any]] = []
    for src, dst in wire_pairs:
        if src == ENTRY_TOKEN:
            aml_src = "ENTRY"
        else:
            aml_src = route_nodes.get(src, id_to_name.get(src, slugify_node_name(src, fallback="node")))
        if dst == EXIT_TOKEN:
            aml_dst = "EXIT"
        else:
            aml_dst = id_to_name.get(dst, slugify_node_name(dst, fallback="node"))

        edge: dict[str, Any] = {"source": aml_src, "target": aml_dst}
        ext_edge = edges_by_pair.get((src, dst))
        if ext_edge is not None:
            cond = _edge_condition(ext_edge)
            if cond:
                edge["condition"] = cond
        out.append(edge)
    return out


def _build_scope_subgraph(
    member_ids: set[str],
    edges: list[ExternalEdge],
    *,
    nodes_by_id: dict[str, ExternalNode],
    id_to_name: dict[str, str],
    loop: bool,
    scope: str,
) -> dict[str, Any]:
    scoped_nodes: list[dict[str, Any]] = []
    for ext_id in sorted(member_ids, key=lambda x: (len(x), x)):
        ext = nodes_by_id.get(ext_id)
        if ext is None or ext.kind in _SKIP_KINDS:
            continue
        name = id_to_name.get(ext_id, slugify_node_name(ext_id, fallback="node"))
        scoped_nodes.append(
            _compat_node(
                ext,
                node_id=name,
                scope=scope,
                aml_kind=_infer_aml_kind(ext),
            )
        )

    out_by_source: dict[str, list[ExternalEdge]] = defaultdict(list)
    internal: list[ExternalEdge] = []
    for edge in edges:
        if edge.source in member_ids and edge.target in member_ids:
            out_by_source[edge.source].append(edge)
            internal.append(edge)

    route_nodes: dict[str, str] = {}
    for src, out_edges in out_by_source.items():
        if needs_logic_switch(out_edges):
            route_nodes[src] = slugify_node_name(f"{id_to_name.get(src, src)}__route", fallback="route")
            scoped_nodes.append(
                {
                    "id": route_nodes[src],
                    "label": "Route",
                    "kind": "agent_switch",
                    "attributes": {
                        "compat_external_id": src,
                        "compat_kind": "route",
                        "compat_scope": scope,
                    },
                }
            )

    scoped_edges: list[dict[str, Any]] = []
    entry_src = "CONTROLLER" if loop else "ENTRY"
    exit_dst = "TERMINATE" if loop else "EXIT"

    for src, out_edges in out_by_source.items():
        if src in route_nodes:
            route_name = route_nodes[src]
            scoped_edges.append({"source": id_to_name[src], "target": route_name})
            for edge in out_edges:
                item: dict[str, Any] = {
                    "source": route_name,
                    "target": id_to_name[edge.target],
                }
                cond = _edge_condition(edge)
                if cond:
                    item["condition"] = cond
                scoped_edges.append(item)
            continue
        for edge in out_edges:
            scoped_edges.append(
                {
                    "source": id_to_name[edge.source],
                    "target": id_to_name[edge.target],
                }
            )

    internal_targets = {e.target for e in internal}
    entry_members = [m for m in member_ids if m not in internal_targets]
    if not entry_members:
        entry_members = list(member_ids)

    for entry in entry_members[:1]:
        scoped_edges.insert(0, {"source": entry_src, "target": id_to_name[entry]})

    for member in member_ids:
        has_out = any(e.source == member for e in internal)
        if not has_out:
            scoped_edges.append({"source": id_to_name[member], "target": exit_dst})

    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for edge in scoped_edges:
        key = (edge["source"], edge["target"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)

    return {"nodes": scoped_nodes, "edges": deduped}


def _loop_node_from_plan(
    plan: LoopPlan,
    *,
    nodes_by_id: dict[str, ExternalNode],
    id_to_name: dict[str, str],
) -> dict[str, Any]:
    loop_name = slugify_node_name(plan.loop_id, fallback="loop")
    scope = f"root/{loop_name}"
    sub = _build_scope_subgraph(
        set(plan.member_ids),
        list(plan.internal_edges),
        nodes_by_id=nodes_by_id,
        id_to_name=id_to_name,
        loop=True,
        scope=scope,
    )
    return _compat_node(
        ExternalNode(id=plan.loop_id, kind="loop", label=loop_name, raw={}),
        node_id=loop_name,
        scope="root",
        aml_kind="loop",
        extra={
            "max_iterations": plan.max_iterations,
            "terminate_condition": f"Imported loop (max {plan.max_iterations} iterations).",
            "sub_graph": sub,
        },
    )


def _dify_inner_subgraph(
    loop_id: str,
    inner: dict[str, Any],
    *,
    nodes_by_id: dict[str, ExternalNode],
    id_to_name: dict[str, str],
) -> dict[str, Any]:
    child_ids: set[str] = set()
    for raw in inner.get("nodes") or []:
        if isinstance(raw, dict) and raw.get("id") is not None:
            child_ids.add(str(raw["id"]))

    member_ids = {cid for cid in child_ids if cid in nodes_by_id}
    if not member_ids:
        member_ids = child_ids

    internal_edges: list[ExternalEdge] = []
    for raw in inner.get("edges") or []:
        if not isinstance(raw, dict):
            continue
        src, dst = raw.get("source"), raw.get("target")
        if src is None or dst is None:
            continue
        if str(src) not in member_ids or str(dst) not in member_ids:
            continue
        internal_edges.append(
            ExternalEdge(
                source=str(src),
                target=str(dst),
                source_handle=str(raw["sourceHandle"]) if raw.get("sourceHandle") is not None else None,
                target_handle=str(raw["targetHandle"]) if raw.get("targetHandle") is not None else None,
                raw=dict(raw),
            )
        )

    loop_name = id_to_name.get(loop_id, slugify_node_name(loop_id, fallback="loop"))
    scope = f"root/{loop_name}"
    return _build_scope_subgraph(
        member_ids,
        internal_edges,
        nodes_by_id=nodes_by_id,
        id_to_name=id_to_name,
        loop=True,
        scope=scope,
    )


def _blueprint_to_aml_graph(blueprint: GraphBlueprint) -> dict[str, Any]:
    if not blueprint.nodes:
        return {"nodes": [], "edges": []}

    skip_ids = _dify_skip_ids(blueprint)
    loop_subgraphs = _dify_loop_subgraphs(blueprint)
    nodes_by_id = {n.id: n for n in blueprint.nodes}
    active_nodes = [n for n in blueprint.nodes if n.id not in skip_ids and n.kind not in _SKIP_KINDS]
    id_to_name = _build_id_map(blueprint, active_nodes=active_nodes)

    loop_plans = plan_loop_regions(blueprint)
    looped_ids = nodes_in_loops(loop_plans)
    plan_for_member = {mid: plan for plan in loop_plans for mid in plan.member_ids}

    emitted_loop_names: set[str] = set()
    aml_nodes: list[dict[str, Any]] = []

    for ext in active_nodes:
        if ext.id in skip_ids or ext.id in looped_ids:
            continue
        if ext.kind in _LOOP_KINDS and ext.id in loop_subgraphs:
            loop_name = id_to_name[ext.id]
            sub = _dify_inner_subgraph(
                ext.id,
                loop_subgraphs[ext.id],
                nodes_by_id=nodes_by_id,
                id_to_name=id_to_name,
            )
            aml_nodes.append(
                _compat_node(
                    ext,
                    node_id=loop_name,
                    scope="root",
                    aml_kind="loop",
                    extra={
                        "max_iterations": 20,
                        "terminate_condition": "Imported Dify loop (compatibility preview).",
                        "sub_graph": sub,
                    },
                )
            )
            emitted_loop_names.add(loop_name)
            continue
        aml_nodes.append(
            _compat_node(
                ext,
                node_id=id_to_name[ext.id],
                scope="root",
                aml_kind=_infer_aml_kind(ext),
            )
        )

    for plan in loop_plans:
        loop_name = slugify_node_name(plan.loop_id, fallback="loop")
        if loop_name in emitted_loop_names:
            continue
        if plan.member_ids <= skip_ids:
            continue
        id_to_name[plan.loop_id] = loop_name
        aml_nodes.append(_loop_node_from_plan(plan, nodes_by_id=nodes_by_id, id_to_name=id_to_name))
        emitted_loop_names.add(loop_name)

    root_ids = {n.id for n in active_nodes if n.id not in looped_ids}
    member_id_set = root_ids | {p.loop_id for p in loop_plans}
    wire_pairs, _ = build_loop_aware_wire_pairs(
        blueprint,
        loop_plans=loop_plans,
        looped_ids=looped_ids,
        plan_for_member=plan_for_member,
        member_id_set=member_id_set,
    )

    filtered_pairs: list[tuple[str, str]] = []
    for src, dst in wire_pairs:
        if src != ENTRY_TOKEN and src in skip_ids:
            continue
        if dst != EXIT_TOKEN and dst in skip_ids:
            continue
        if src in skip_ids or dst in skip_ids:
            continue
        filtered_pairs.append((src, dst))

    aml_edges = _wire_pairs_to_aml_edges(
        filtered_pairs,
        id_to_name=id_to_name,
        edges_by_pair=_index_edges(blueprint.edges),
    )

    if not any(e.get("source") == "ENTRY" for e in aml_edges) and aml_nodes:
        aml_edges.insert(0, {"source": "ENTRY", "target": aml_nodes[0]["id"]})
    if not any(e.get("target") == "EXIT" for e in aml_edges) and aml_nodes:
        aml_edges.append({"source": aml_nodes[-1]["id"], "target": "EXIT"})

    return {"nodes": aml_nodes, "edges": aml_edges}


def _append_attribute(parent: ET.Element, name: str, value: Any) -> None:
    attr = ET.SubElement(parent, "attribute", {"name": name})
    if isinstance(value, (dict, list, tuple)):
        attr.text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    elif value is not None:
        attr.set("value", str(value))


def _append_attributes(parent: ET.Element, node: dict[str, Any]) -> None:
    metadata = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
    if not metadata:
        return
    attrs = ET.SubElement(parent, "attributes")
    for key, value in metadata.items():
        _append_attribute(attrs, str(key), value)


def _endpoint_from_runtime(endpoint: str, *, loop_scope: bool) -> str:
    token = str(endpoint or "").strip()
    upper = token.upper()
    if loop_scope:
        if upper == "CONTROLLER":
            return "controller"
        if upper == "TERMINATE":
            return "terminate"
        return token
    if upper == "ENTRY":
        return "entry"
    if upper == "EXIT":
        return "exit"
    return token


def _append_edge(parent: ET.Element, edge: dict[str, Any], *, loop_scope: bool) -> None:
    src = _endpoint_from_runtime(str(edge.get("source") or ""), loop_scope=loop_scope)
    dst = _endpoint_from_runtime(str(edge.get("target") or ""), loop_scope=loop_scope)
    if not src or not dst:
        return
    attrs = {"from": src, "to": dst}
    condition = edge.get("condition")
    if condition is not None and str(condition).strip():
        attrs["match"] = str(condition).strip()
    el = ET.SubElement(parent, "edge", attrs)
    ET.SubElement(el, "keys")


def _append_node(parent: ET.Element, node: dict[str, Any], *, loop_scope: bool) -> None:
    node_id = str(node.get("id") or "").strip()
    if not node_id:
        return
    label = str(node.get("label") or node_id).strip()
    kind = str(node.get("kind") or "custom_node").strip()

    if kind == "loop":
        el = ET.SubElement(parent, "loop", {"id": node_id})
        if node.get("max_iterations") is not None:
            el.set("max_iterations", str(node["max_iterations"]))
        terminate = node.get("terminate_condition")
        if terminate:
            ET.SubElement(el, "terminate", {"match": str(terminate)})
        sub_graph = node.get("sub_graph")
        if isinstance(sub_graph, dict):
            _append_graph_scope(el, sub_graph, loop_scope=True)
    elif kind == "graph":
        el = ET.SubElement(parent, "graph", {"id": node_id})
        sub_graph = node.get("sub_graph")
        if isinstance(sub_graph, dict):
            _append_graph_scope(el, sub_graph, loop_scope=False)
    elif kind == "agent_switch":
        el = ET.SubElement(parent, "agent_switch", {"id": node_id})
    elif kind == "logic_switch":
        el = ET.SubElement(parent, "logic_switch", {"id": node_id})
    elif kind == "agent":
        el = ET.SubElement(parent, "agent", {"id": node_id})
        agent_ref = str(node.get("agent") or node_id).strip()
        if agent_ref:
            el.set("ref", f"#{agent_ref}")
    else:
        el = ET.SubElement(parent, "custom_node", {"id": node_id})
        forward = str(node.get("forward") or "").strip()
        if forward:
            el.set("forward", forward)

    if label and label != node_id:
        el.set("label", label)
    _append_attributes(el, node)


def _append_graph_scope(parent: ET.Element, graph: dict[str, Any], *, loop_scope: bool) -> None:
    nodes_el = ET.SubElement(parent, "nodes")
    for node in graph.get("nodes", []) if isinstance(graph.get("nodes"), list) else []:
        if isinstance(node, dict):
            _append_node(nodes_el, node, loop_scope=loop_scope)
    edges_el = ET.SubElement(parent, "edges")
    for edge in graph.get("edges", []) if isinstance(graph.get("edges"), list) else []:
        if isinstance(edge, dict):
            _append_edge(edges_el, edge, loop_scope=loop_scope)


def blueprint_to_aml_document(
    blueprint: GraphBlueprint,
    *,
    source: str | None = None,
    document_id: str = "masfactory.compatibility.graph",
    root_graph_id: str = "root",
) -> str:
    """Serialize a compatibility blueprint directly as AML v0.2."""
    aml = ET.Element(
        "aml",
        {
            "version": "0.2",
            "profile": "masfactory",
            "kind": "graph",
            "id": document_id,
        },
    )
    definitions = ET.SubElement(aml, "definitions")
    graphs = ET.SubElement(definitions, "graphs")
    root_graph = ET.SubElement(graphs, "graph", {"id": root_graph_id, "kind": "root"})
    if source:
        metadata = ET.SubElement(root_graph, "metadata")
        ET.SubElement(metadata, "source").text = source
    _append_graph_scope(root_graph, _blueprint_to_aml_graph(blueprint), loop_scope=False)
    ET.indent(aml, space="  ")
    return ET.tostring(aml, encoding="unicode") + "\n"


def blueprint_to_graph_design_document_via_aml(
    blueprint: GraphBlueprint,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    """Deprecated graph_design wrapper implemented as blueprint -> AML -> graph_design."""
    from masfactory.aml import aml_to_graph_design

    aml = blueprint_to_aml_document(blueprint, source=source)
    doc: dict[str, Any] = {"graph_design": aml_to_graph_design(aml, strict=True)}
    meta: dict[str, Any] = {"format": "graph_design_v4", "exporter": "masfactory.compatibility.legacy"}
    if source:
        meta["source"] = source
    if blueprint.metadata:
        meta["import_metadata"] = blueprint.metadata
    doc["compatibility_export"] = meta
    return doc


def _compatibility_metadata(blueprint: GraphBlueprint, *, source: str | None) -> dict[str, Any]:
    compatibility: dict[str, Any] = {
        "source": source or "compatibility_aml",
        "external_nodes": {
            ext.id: {"kind": ext.kind, "label": ext.label} for ext in blueprint.nodes
        },
        "external_edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "source_handle": edge.source_handle,
                "target_handle": edge.target_handle,
            }
            for edge in blueprint.edges
        ],
    }
    if blueprint.metadata:
        compatibility.update(blueprint.metadata)
    return compatibility


def _default_compile_model():
    from masfactory.adapters.model import Model
    from masfactory.adapters.model.base import ModelResponseType

    class _CompatibilityAmlModel(Model):
        def __init__(self):
            super().__init__(model_name="compatibility-aml")

        def invoke(
            self,
            messages: list[dict],
            tools: list[dict] | None,
            settings: dict | None = None,
            **kwargs,
        ) -> dict:
            return {"type": ModelResponseType.CONTENT, "content": "YES"}

    return _CompatibilityAmlModel()


def blueprint_to_graph_via_aml(
    blueprint: GraphBlueprint,
    *,
    graph_name: str,
    source: str | None = None,
    model: Any | None = None,
    tools: list[Callable] | None = None,
):
    """Compile a compatibility blueprint through the AML runtime compiler."""
    from masfactory.components.graphs.graph import Graph
    from masfactory.components.vibe.compiler import compile_aml

    graph = Graph(
        name=graph_name,
        attributes={"compatibility": _compatibility_metadata(blueprint, source=source)},
    )
    compile_aml(
        target_graph=graph,
        aml=blueprint_to_aml_document(blueprint, source=source, root_graph_id=graph_name),
        model=model or _default_compile_model(),
        tools=tools,
    )
    return graph


def write_aml(path: str | Path, document: str) -> Path:
    """Write an AML document to disk (UTF-8)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document, encoding="utf-8")
    return out


def export_aml_for_blueprint(
    blueprint: GraphBlueprint,
    path: str | Path,
    *,
    source: str | None = None,
    document_id: str = "masfactory.compatibility.graph",
    root_graph_id: str = "root",
) -> Path:
    """Serialize a blueprint as a Visualizer-previewable AML file."""
    return write_aml(
        path,
        blueprint_to_aml_document(
            blueprint,
            source=source,
            document_id=document_id,
            root_graph_id=root_graph_id,
        ),
    )
