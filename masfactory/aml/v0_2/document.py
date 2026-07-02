from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

AML_VERSION = "0.2"

_NODE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class AmlEdge:
    source: str
    target: str
    condition: str | None = None
    condition_kind: str | None = None
    keys: dict[str, str] | None = None


@dataclass(frozen=True)
class AmlNode:
    id: str
    kind: str
    label: str
    agent_ref: str | None = None
    instructions: str | None = None
    prompt_template: str | None = None
    forward: str | None = None
    ref: str | None = None
    implementation: str | None = None
    max_iterations: int | None = None
    terminate_condition_prompt: str | None = None
    terminate_condition_expr: str | None = None
    pull_keys: dict[str, str] | None = None
    push_keys: dict[str, str] | None = None
    attributes: dict[str, Any] | None = None
    sub_graph: "AmlGraph | None" = None


@dataclass(frozen=True)
class AmlGraph:
    id: str
    kind: str | None
    nodes: tuple[AmlNode, ...]
    edges: tuple[AmlEdge, ...]


@dataclass(frozen=True)
class AmlDocument:
    id: str
    version: str
    root_graph: AmlGraph
    agent_definitions: dict[str, dict[str, str]]


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


def _parse_xml(source: str | Path) -> ET.Element:
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


def _endpoint_to_runtime(endpoint: str, *, loop_scope: bool) -> str:
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


def _key_attributes(element: ET.Element) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    attrs_el = _first_direct(element, "attributes")
    if attrs_el is None:
        return None, None
    return (
        _fields_from_container(_first_direct(attrs_el, "pull_keys")),
        _fields_from_container(_first_direct(attrs_el, "push_keys")),
    )


def _edge_keys(edge_el: ET.Element) -> dict[str, str]:
    keys = _first_direct(edge_el, "keys")
    if keys is None:
        return {}
    fields = _fields_from_container(keys)
    return fields or {}


def _condition_attrs(edge_el: ET.Element) -> tuple[str | None, str | None]:
    if "if" in edge_el.attrib and str(edge_el.attrib["if"]).strip():
        return str(edge_el.attrib["if"]).strip(), "if"
    if "match" in edge_el.attrib and str(edge_el.attrib["match"]).strip():
        return str(edge_el.attrib["match"]).strip(), "match"
    return None, None


def _graph_containers(graph_el: ET.Element) -> tuple[ET.Element | None, ET.Element | None]:
    return _first_direct(graph_el, "nodes"), _first_direct(graph_el, "edges")


def _parse_node(
    element: ET.Element,
    *,
    agent_defs: dict[str, dict[str, str]],
    strict: bool,
) -> AmlNode | None:
    tag = _local_name(element.tag)
    node_id = (element.attrib.get("id") or element.attrib.get("name") or "").strip()
    if not node_id:
        if strict:
            raise ValueError(f"<{tag}> node is missing required id")
        return None

    label = (element.attrib.get("label") or element.attrib.get("name") or node_id).strip()
    pull_keys, push_keys = _key_attributes(element)
    attributes = _node_attributes(element)

    if tag == "agent":
        ref = _ref_id(element.attrib.get("ref")) or node_id
        definition = agent_defs.get(ref, {})
        instructions = (
            element.attrib.get("instructions")
            or _text_child(element, "instructions")
            or definition.get("instructions")
            or f"Execute AML agent node '{node_id}'."
        )
        prompt_template = (
            element.attrib.get("prompt_template")
            or _text_child(element, "prompt_template")
            or definition.get("prompt_template")
        )
        return AmlNode(
            id=node_id,
            kind="agent",
            label=label,
            agent_ref=ref,
            instructions=str(instructions).strip(),
            prompt_template=str(prompt_template).strip() if prompt_template else None,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes or None,
        )

    if tag == "custom_node":
        return AmlNode(
            id=node_id,
            kind="custom_node",
            label=label,
            forward=(element.attrib.get("forward") or "").strip() or None,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes or None,
        )

    if tag in {"logic_switch", "agent_switch", "switch"}:
        kind = tag if tag != "switch" else "agent_switch"
        return AmlNode(
            id=node_id,
            kind=kind,
            label=label,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes or None,
        )

    if tag == "loop":
        max_iterations = int(element.attrib.get("max_iterations") or 3)
        terminate_prompt: str | None = None
        terminate_expr: str | None = None
        terminate = _first_direct(element, "terminate")
        if terminate is not None:
            if (terminate.attrib.get("match") or "").strip():
                terminate_prompt = terminate.attrib["match"].strip()
            elif (terminate.attrib.get("if") or "").strip():
                terminate_expr = terminate.attrib["if"].strip()
            else:
                text = "".join(terminate.itertext()).strip()
                if text:
                    terminate_prompt = text
        return AmlNode(
            id=node_id,
            kind="loop",
            label=label,
            max_iterations=max_iterations,
            terminate_condition_prompt=terminate_prompt,
            terminate_condition_expr=terminate_expr,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes or None,
            sub_graph=_parse_graph_scope(
                element,
                agent_defs=agent_defs,
                strict=strict,
                loop_scope=True,
            ),
        )

    if tag == "graph":
        nodes_el, edges_el = _graph_containers(element)
        sub_graph = None
        if nodes_el is not None or edges_el is not None:
            sub_graph = _parse_graph_scope(
                element,
                agent_defs=agent_defs,
                strict=strict,
                loop_scope=False,
            )
        return AmlNode(
            id=node_id,
            kind="graph",
            label=label,
            ref=_ref_id(element.attrib.get("ref")) or None,
            implementation=(element.attrib.get("implementation") or "").strip() or None,
            pull_keys=pull_keys,
            push_keys=push_keys,
            attributes=attributes or None,
            sub_graph=sub_graph,
        )

    return None


def _parse_graph_scope(
    graph_el: ET.Element,
    *,
    agent_defs: dict[str, dict[str, str]],
    strict: bool,
    loop_scope: bool,
) -> AmlGraph:
    nodes: list[AmlNode] = []
    edges: list[AmlEdge] = []

    nodes_el, edges_el = _graph_containers(graph_el)
    if nodes_el is not None:
        for child in _direct_children(nodes_el):
            parsed = _parse_node(child, agent_defs=agent_defs, strict=strict)
            if parsed is not None:
                nodes.append(parsed)

    if edges_el is not None:
        for edge_el in _direct_children(edges_el, "edge"):
            src = _endpoint_to_runtime(edge_el.attrib.get("from") or "", loop_scope=loop_scope)
            dst = _endpoint_to_runtime(edge_el.attrib.get("to") or "", loop_scope=loop_scope)
            if not src or not dst:
                if strict:
                    raise ValueError("<edge> requires non-empty from/to")
                continue
            condition, condition_kind = _condition_attrs(edge_el)
            edges.append(
                AmlEdge(
                    source=src,
                    target=dst,
                    condition=condition,
                    condition_kind=condition_kind,
                    keys=_edge_keys(edge_el),
                )
            )

    return AmlGraph(
        id=(graph_el.attrib.get("id") or graph_el.attrib.get("name") or "graph").strip(),
        kind=(graph_el.attrib.get("kind") or "").strip() or None,
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


def parse_aml_document(source: str | Path, *, strict: bool = False) -> AmlDocument:
    """Parse AML v0.2 into an AML-native document model."""
    root = _parse_xml(source)
    agent_defs = _definition_agents(root)
    graph = _find_root_graph(root)
    document = AmlDocument(
        id=(root.attrib.get("id") or "aml.document").strip(),
        version=(root.attrib.get("version") or AML_VERSION).strip(),
        root_graph=_parse_graph_scope(graph, agent_defs=agent_defs, strict=strict, loop_scope=False),
        agent_definitions=agent_defs,
    )
    if strict:
        validate_aml_document(document)
    return document


def _validate_node(node: AmlNode, *, path: str) -> None:
    if not node.id or not _NODE_NAME_PATTERN.match(node.id):
        raise ValueError(f"{path}: invalid node id '{node.id}'")
    if node.kind not in {"agent", "custom_node", "logic_switch", "agent_switch", "loop", "graph"}:
        raise ValueError(f"{path}: unsupported node kind '{node.kind}'")
    if node.kind == "agent" and not (node.instructions or "").strip():
        raise ValueError(f"{path}: agent node requires non-empty instructions")
    if node.max_iterations is not None and node.max_iterations <= 0:
        raise ValueError(f"{path}: max_iterations must be positive")


def _validate_graph_scope(
    graph: AmlGraph,
    *,
    loop_scope: bool,
    path: str,
    allow_empty: bool = False,
) -> None:
    node_by_id: dict[str, AmlNode] = {}
    for index, node in enumerate(graph.nodes):
        _validate_node(node, path=f"{path}.nodes[{index}]")
        if node.id in node_by_id:
            raise ValueError(f"{path}.nodes[{index}]: duplicate node '{node.id}'")
        node_by_id[node.id] = node

        if node.kind == "loop":
            if node.sub_graph is None:
                raise ValueError(f"{path}.nodes[{index}]: loop node requires sub_graph")
            _validate_graph_scope(
                node.sub_graph,
                loop_scope=True,
                path=f"{path}.nodes[{node.id}].sub_graph",
                allow_empty=False,
            )
        elif node.kind == "graph" and node.sub_graph is not None:
            _validate_graph_scope(
                node.sub_graph,
                loop_scope=False,
                path=f"{path}.nodes[{node.id}].sub_graph",
                allow_empty=True,
            )

    if not graph.nodes:
        if allow_empty and not graph.edges:
            return
        raise ValueError(f"{path}: graph must contain at least one node")

    for index, edge in enumerate(graph.edges):
        src = edge.source.strip()
        dst = edge.target.strip()
        if not src or not dst:
            raise ValueError(f"{path}.edges[{index}]: source/target must be non-empty strings")
        if loop_scope:
            src_ok = src == "CONTROLLER" or src in node_by_id
            dst_ok = dst in {"CONTROLLER", "TERMINATE"} or dst in node_by_id
            if src == "TERMINATE":
                raise ValueError(f"{path}.edges[{index}]: TERMINATE cannot be an edge source")
        else:
            src_ok = src == "ENTRY" or src in node_by_id
            dst_ok = dst == "EXIT" or dst in node_by_id
        if not src_ok:
            raise ValueError(f"{path}.edges[{index}]: unknown source '{src}'")
        if not dst_ok:
            raise ValueError(f"{path}.edges[{index}]: unknown target '{dst}'")
        source_node = node_by_id.get(src)
        if source_node is not None and source_node.kind in {"logic_switch", "agent_switch"}:
            if not (edge.condition or "").strip():
                raise ValueError(f"{path}.edges[{index}]: switch edge '{src}->{dst}' requires condition")

    if loop_scope:
        if not any(edge.source == "CONTROLLER" and edge.target in node_by_id for edge in graph.edges):
            raise ValueError(f"{path}: Loop.sub_graph must contain at least one CONTROLLER -> <node> edge")
        if not any(edge.target == "CONTROLLER" and edge.source in node_by_id for edge in graph.edges):
            raise ValueError(f"{path}: Loop.sub_graph must contain at least one <node> -> CONTROLLER edge")
    else:
        if not any(edge.source == "ENTRY" and edge.target in node_by_id for edge in graph.edges):
            raise ValueError(f"{path}: graph must contain at least one entry -> <node> edge")
        if not any(edge.target == "EXIT" and edge.source in node_by_id for edge in graph.edges):
            raise ValueError(f"{path}: graph must contain at least one <node> -> exit edge")


def validate_aml_document(document: AmlDocument) -> None:
    """Validate the AML-native document model before runtime compilation."""
    _validate_graph_scope(document.root_graph, loop_scope=False, path="aml.root_graph")
