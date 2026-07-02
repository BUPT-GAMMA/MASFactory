from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

AML_VERSION = "0.2"


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _read_text(source: str | Path) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    text = str(source)
    if text.lstrip().startswith("<"):
        return text
    path = Path(text)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return text


def _parse(source: str | Path) -> ET.Element:
    text = _read_text(source)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid AML XML: {exc}") from exc
    if _local_name(root.tag) != "aml":
        raise ValueError("AML document root must be <aml>")
    version = (root.attrib.get("version") or AML_VERSION).strip()
    if version != AML_VERSION:
        raise ValueError(f"Unsupported AML v0.2 parser input version '{version}'")
    return root


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


def _find_root_graph(root: ET.Element) -> ET.Element:
    graphs: list[ET.Element] = []
    for element in root.iter():
        if _local_name(element.tag) == "graph":
            graphs.append(element)
    for graph in graphs:
        if (graph.attrib.get("kind") or "").strip() == "root":
            return graph
    if graphs:
        return graphs[0]
    raise ValueError("AML document must contain a <graph> element")


def _text_child(parent: ET.Element, name: str) -> str:
    child = _first_direct(parent, name)
    if child is None:
        return ""
    return "".join(child.itertext()).strip()


def _definition_agents(root: ET.Element) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for agents in root.iter():
        if _local_name(agents.tag) != "agents":
            continue
        for agent in _direct_children(agents, "agent"):
            agent_id = (agent.attrib.get("id") or "").strip()
            if not agent_id:
                continue
            out[agent_id] = {
                "instructions": (agent.attrib.get("instructions") or _text_child(agent, "instructions")).strip(),
                "prompt_template": (agent.attrib.get("prompt_template") or _text_child(agent, "prompt_template")).strip(),
            }
    return out


def _ref_id(value: str | None) -> str:
    ref = (value or "").strip()
    if ref.startswith("#"):
        return ref[1:]
    return ref


def _endpoint_to_graph_design(endpoint: str, *, loop_scope: bool) -> str:
    ep = str(endpoint or "").strip()
    lower = ep.lower()
    if loop_scope:
        if lower == "controller":
            return "CONTROLLER"
        if lower == "terminate":
            return "TERMINATE"
        return ep
    if lower == "entry":
        return "ENTRY"
    if lower == "exit":
        return "EXIT"
    return ep


def _endpoint_from_graph_design(endpoint: str, *, loop_scope: bool) -> str:
    ep = str(endpoint or "").strip()
    upper = ep.upper()
    if loop_scope:
        if upper == "CONTROLLER":
            return "controller"
        if upper == "TERMINATE":
            return "terminate"
        return ep
    if upper in {"ENTRY", "START"}:
        return "entry"
    if upper in {"EXIT", "END"}:
        return "exit"
    return ep


def _fields_from_container(container: ET.Element | None) -> dict[str, str] | None:
    if container is None:
        return None
    mode = (container.attrib.get("mode") or "").strip().lower()
    if mode == "all":
        return None
    fields: dict[str, str] = {}
    for field in _direct_children(container, "field"):
        name = (field.attrib.get("name") or "").strip()
        if not name:
            continue
        desc = (field.attrib.get("description") or field.attrib.get("type") or "").strip()
        fields[name] = desc
    return fields


def _node_attributes(element: ET.Element) -> dict[str, Any]:
    attrs_el = _first_direct(element, "attributes")
    if attrs_el is None:
        return {}
    out: dict[str, Any] = {}
    for attr in _direct_children(attrs_el, "attribute"):
        name = (attr.attrib.get("name") or "").strip()
        if not name:
            continue
        if "value" in attr.attrib:
            out[name] = attr.attrib.get("value")
        elif attr.text and attr.text.strip():
            out[name] = attr.text.strip()
    return out


def _apply_key_attributes(node: dict[str, Any], element: ET.Element) -> None:
    attrs_el = _first_direct(element, "attributes")
    if attrs_el is None:
        return
    pull = _fields_from_container(_first_direct(attrs_el, "pull_keys"))
    push = _fields_from_container(_first_direct(attrs_el, "push_keys"))
    if pull is not None:
        node["pull_keys"] = pull
    if push is not None:
        node["push_keys"] = push
    metadata = _node_attributes(element)
    if metadata:
        node["attributes"] = metadata


def _edge_keys(edge_el: ET.Element) -> dict[str, str]:
    keys = _first_direct(edge_el, "keys")
    if keys is None:
        return {}
    fields = _fields_from_container(keys)
    return fields or {}


def _condition_attrs(edge_el: ET.Element) -> dict[str, Any]:
    if "if" in edge_el.attrib and str(edge_el.attrib["if"]).strip():
        return {
            "condition": str(edge_el.attrib["if"]).strip(),
            "condition_kind": "if",
        }
    if "match" in edge_el.attrib and str(edge_el.attrib["match"]).strip():
        return {
            "condition": str(edge_el.attrib["match"]).strip(),
            "condition_kind": "match",
        }
    return {}


def _graph_containers(graph_el: ET.Element) -> tuple[ET.Element | None, ET.Element | None]:
    return _first_direct(graph_el, "nodes"), _first_direct(graph_el, "edges")


def _parse_node(
    element: ET.Element,
    *,
    root: ET.Element,
    agent_defs: dict[str, dict[str, str]],
    strict: bool,
) -> dict[str, Any] | None:
    tag = _local_name(element.tag)
    node_id = (element.attrib.get("id") or element.attrib.get("name") or "").strip()
    if not node_id:
        if strict:
            raise ValueError(f"<{tag}> node is missing required id")
        return None

    label = (element.attrib.get("label") or element.attrib.get("name") or node_id).strip()
    node: dict[str, Any]

    if tag == "agent":
        ref = _ref_id(element.attrib.get("ref")) or node_id
        definition = agent_defs.get(ref, {})
        instructions = (
            element.attrib.get("instructions")
            or _text_child(element, "instructions")
            or definition.get("instructions")
            or f"Execute AML agent node '{node_id}'."
        )
        node = {
            "id": node_id,
            "name": node_id,
            "type": "Action",
            "label": label,
            "agent": ref,
            "instructions": str(instructions).strip(),
        }
        prompt_template = element.attrib.get("prompt_template") or _text_child(element, "prompt_template") or definition.get("prompt_template")
        if prompt_template:
            node["prompt_template"] = str(prompt_template).strip()
    elif tag == "custom_node":
        node = {
            "id": node_id,
            "name": node_id,
            "type": "CustomNode",
            "label": label,
        }
        forward = (element.attrib.get("forward") or "").strip()
        if forward:
            node["forward"] = forward
    elif tag in {"logic_switch", "agent_switch", "switch"}:
        node = {
            "id": node_id,
            "name": node_id,
            "type": "Switch",
            "label": label,
        }
        node["switch_kind"] = tag
    elif tag == "loop":
        node = {
            "id": node_id,
            "name": node_id,
            "type": "Loop",
            "label": label,
            "max_iterations": int(element.attrib.get("max_iterations") or 3),
        }
        terminate = _first_direct(element, "terminate")
        if terminate is not None:
            if (terminate.attrib.get("match") or "").strip():
                node["terminate_condition_prompt"] = terminate.attrib["match"].strip()
            elif (terminate.attrib.get("if") or "").strip():
                node["terminate_condition_expr"] = terminate.attrib["if"].strip()
            else:
                text = "".join(terminate.itertext()).strip()
                if text:
                    node["terminate_condition_prompt"] = text
        node["sub_graph"] = _parse_graph_scope(element, root=root, agent_defs=agent_defs, strict=strict, loop_scope=True)
    elif tag == "graph":
        node = {
            "id": node_id,
            "name": node_id,
            "type": "Subgraph",
            "label": label,
        }
        ref = _ref_id(element.attrib.get("ref"))
        implementation = (element.attrib.get("implementation") or "").strip()
        if ref:
            node["ref"] = ref
        if implementation:
            node["implementation"] = implementation
        nodes_el, edges_el = _graph_containers(element)
        if nodes_el is not None or edges_el is not None:
            node["sub_graph"] = _parse_graph_scope(element, root=root, agent_defs=agent_defs, strict=strict, loop_scope=False)
    else:
        return None

    _apply_key_attributes(node, element)
    return node


def _parse_graph_scope(
    graph_el: ET.Element,
    *,
    root: ET.Element,
    agent_defs: dict[str, dict[str, str]],
    strict: bool,
    loop_scope: bool,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    nodes_el, edges_el = _graph_containers(graph_el)
    if nodes_el is not None:
        for child in _direct_children(nodes_el):
            parsed = _parse_node(child, root=root, agent_defs=agent_defs, strict=strict)
            if parsed is not None:
                nodes.append(parsed)

    if edges_el is not None:
        for edge_el in _direct_children(edges_el, "edge"):
            src = _endpoint_to_graph_design(edge_el.attrib.get("from") or "", loop_scope=loop_scope)
            dst = _endpoint_to_graph_design(edge_el.attrib.get("to") or "", loop_scope=loop_scope)
            if not src or not dst:
                if strict:
                    raise ValueError("<edge> requires non-empty from/to")
                continue
            edge: dict[str, Any] = {"source": src, "target": dst}
            edge.update(_condition_attrs(edge_el))
            edge["keys"] = _edge_keys(edge_el)
            edges.append(edge)

    return {"nodes": nodes, "edges": edges}


def aml_to_graph_design(source: str | Path, *, strict: bool = False) -> dict[str, Any]:
    """Convert an AML v0.2 document to the legacy graph_design `{nodes, edges}` shape."""
    root = _parse(source)
    agent_defs = _definition_agents(root)
    graph = _find_root_graph(root)
    return _parse_graph_scope(graph, root=root, agent_defs=agent_defs, strict=strict, loop_scope=False)


def _set_if(element: ET.Element, name: str, value: Any) -> None:
    if value is None:
        return
    text = str(value)
    if text:
        element.set(name, text)


def _append_fields(parent: ET.Element, tag: str, keys: Any) -> None:
    if keys is None:
        return
    container = ET.SubElement(parent, tag, {"mode": "keys"})
    if isinstance(keys, dict):
        for name, desc in keys.items():
            attrs = {"name": str(name)}
            if desc is not None and str(desc):
                attrs["description"] = str(desc)
            ET.SubElement(container, "field", attrs)
    elif isinstance(keys, list):
        for name in keys:
            ET.SubElement(container, "field", {"name": str(name)})


def _append_node_attributes(parent: ET.Element, node: dict[str, Any]) -> None:
    has_pull = "pull_keys" in node or "input_fields" in node
    has_push = "push_keys" in node or "output_fields" in node
    metadata = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
    if not has_pull and not has_push and not metadata:
        return
    attrs = ET.SubElement(parent, "attributes")
    if has_pull:
        _append_fields(attrs, "pull_keys", node.get("pull_keys", node.get("input_fields")))
    if has_push:
        _append_fields(attrs, "push_keys", node.get("push_keys", node.get("output_fields")))
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            attr = ET.SubElement(attrs, "attribute", {"name": str(key)})
            if isinstance(value, (dict, list)):
                attr.text = json.dumps(value, ensure_ascii=False)
            elif value is not None:
                attr.set("value", str(value))


def _append_node(parent: ET.Element, node: dict[str, Any], *, loop_scope: bool) -> None:
    name = str(node.get("name") or node.get("id") or "").strip()
    if not name:
        return
    raw_type = str(node.get("type") or "Action").strip()
    label = str(node.get("label") or name).strip()

    if raw_type in {"Action", "Agent"}:
        el = ET.SubElement(parent, "agent", {"id": name})
        _set_if(el, "ref", f"#{node.get('agent')}" if node.get("agent") else None)
    elif raw_type in {"CustomNode", "custom_node"}:
        el = ET.SubElement(parent, "custom_node", {"id": name})
        _set_if(el, "forward", node.get("forward") or node.get("binding") or node.get("forward_body"))
    elif raw_type in {"Switch", "LogicSwitch"}:
        el = ET.SubElement(parent, "logic_switch", {"id": name})
    elif raw_type == "AgentSwitch":
        el = ET.SubElement(parent, "agent_switch", {"id": name})
    elif raw_type == "Loop":
        el = ET.SubElement(parent, "loop", {"id": name})
        _set_if(el, "max_iterations", node.get("max_iterations"))
        term = node.get("terminate_condition_prompt") or node.get("terminate_condition")
        if term:
            ET.SubElement(el, "terminate", {"match": str(term)})
        sub_graph = node.get("sub_graph")
        if isinstance(sub_graph, dict):
            _append_graph_scope(el, sub_graph, loop_scope=True)
    elif raw_type in {"Subgraph", "Graph"}:
        el = ET.SubElement(parent, "graph", {"id": name})
        _set_if(el, "ref", node.get("ref"))
        _set_if(el, "implementation", node.get("implementation"))
        sub_graph = node.get("sub_graph")
        if isinstance(sub_graph, dict):
            _append_graph_scope(el, sub_graph, loop_scope=False)
    else:
        el = ET.SubElement(parent, "custom_node", {"id": name})
        _set_if(el, "forward", node.get("forward") or node.get("binding"))

    if label and label != name:
        el.set("label", label)
    _append_node_attributes(el, node)


def _append_edge(parent: ET.Element, edge: dict[str, Any], *, loop_scope: bool) -> None:
    src = _endpoint_from_graph_design(str(edge.get("source") or edge.get("from") or ""), loop_scope=loop_scope)
    dst = _endpoint_from_graph_design(str(edge.get("target") or edge.get("to") or ""), loop_scope=loop_scope)
    if not src or not dst:
        return
    attrs = {"from": src, "to": dst}
    cond = edge.get("condition")
    if cond is not None and str(cond).strip():
        kind = str(edge.get("condition_kind") or "").strip()
        attrs["if" if kind == "if" else "match"] = str(cond).strip()
    el = ET.SubElement(parent, "edge", attrs)
    keys = edge.get("keys", edge.get("key"))
    if keys is not None:
        _append_fields(el, "keys", keys)
    else:
        ET.SubElement(el, "keys")


def _append_graph_scope(parent: ET.Element, graph: dict[str, Any], *, loop_scope: bool) -> None:
    nodes_el = ET.SubElement(parent, "nodes")
    for node in graph.get("nodes", []) if isinstance(graph.get("nodes"), list) else []:
        if isinstance(node, dict):
            _append_node(nodes_el, node, loop_scope=loop_scope)
    edges_el = ET.SubElement(parent, "edges")
    for edge in graph.get("edges", []) if isinstance(graph.get("edges"), list) else []:
        if isinstance(edge, dict):
            _append_edge(edges_el, edge, loop_scope=loop_scope)


def graph_design_to_aml_document(
    graph_design: dict[str, Any],
    *,
    document_id: str = "masfactory.compatibility.graph",
    root_graph_id: str = "root",
    source: str | None = None,
) -> str:
    """Serialize a legacy graph_design object as AML v0.2."""
    graph = graph_design.get("graph_design") if isinstance(graph_design.get("graph_design"), dict) else graph_design
    aml = ET.Element(
        "aml",
        {
            "version": AML_VERSION,
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
    _append_graph_scope(root_graph, graph, loop_scope=False)
    ET.indent(aml, space="  ")
    return ET.tostring(aml, encoding="unicode") + "\n"
