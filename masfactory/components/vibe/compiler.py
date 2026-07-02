from __future__ import annotations

import ast
import inspect
import importlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from masfactory import (
    Agent,
    AgentSwitch,
    CustomNode,
    Graph,
    LogicSwitch,
    Loop,
    Model,
    ParagraphMessageFormatter,
    TwinsFieldTextFormatter,
)
from masfactory.aml import (
    AmlDocument,
    AmlGraph,
    AmlNode,
    aml_to_graph_design,
    graph_design_to_aml_document,
    parse_aml_document,
    validate_aml_document,
)


_BUILTIN_ENTRY = "ENTRY"
_BUILTIN_EXIT = "EXIT"
_BUILTIN_CONTROLLER = "CONTROLLER"
_BUILTIN_TERMINATE = "TERMINATE"

_LEGACY_START = "START"
_LEGACY_END = "END"
_ACTION = "Action"
_SWITCH = "Switch"
_LOOP = "Loop"
_SUBGRAPH = "Subgraph"
_CUSTOM_NODE = "CustomNode"
_ALLOWED_TYPES = {_ACTION, _SWITCH, _LOOP, _SUBGRAPH, _CUSTOM_NODE}

_NODE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_THINKING_BLOCK_PATTERN = re.compile(
    r"<\s*(think|thinking)\s*>.*?<\s*/\s*\1\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_SAFE_EXPR_GLOBALS: dict[str, Any] = {
    "__builtins__": {
        "all": all,
        "any": any,
        "bool": bool,
        "float": float,
        "int": int,
        "len": len,
        "max": max,
        "min": min,
        "str": str,
        "sum": sum,
    }
}


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("expected a list of non-empty strings")
        out.append(item.strip())
    return out


def _normalize_keys_dict(value: Any, *, path: str) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, list):
        out: dict[str, str] = {}
        for i, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"{path}: expected a list of non-empty strings")
            out[item.strip()] = ""
        return out
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a dict or list")
    out: dict[str, str] = {}
    for k, v in value.items():
        key = str(k).strip()
        if not key:
            raise ValueError(f"{path}: empty key")
        if v is None:
            out[key] = ""
        elif isinstance(v, str):
            out[key] = v
        else:
            out[key] = str(v)
    return out


def _tool_map(tools: list[Callable] | None) -> dict[str, Callable]:
    by_name: dict[str, Callable] = {}
    for tool in tools or []:
        name = getattr(tool, "__name__", None)
        if isinstance(name, str) and name.strip():
            by_name[name.strip()] = tool
    return by_name


def _resolve_python_binding(binding: Any) -> Callable | None:
    if not isinstance(binding, str) or not binding.strip():
        return None
    spec = binding.strip()
    if spec.startswith("python:"):
        spec = spec[len("python:") :]
    if ":" in spec:
        module_name, attr_name = spec.split(":", 1)
    else:
        module_name, _, attr_name = spec.rpartition(".")
    if not module_name or not attr_name:
        raise ValueError(f"Invalid Python binding '{binding}'")
    module = importlib.import_module(module_name)
    target: Any = module
    for part in attr_name.split("."):
        target = getattr(target, part)
    if not callable(target):
        raise TypeError(f"Python binding '{binding}' resolved to non-callable {type(target).__name__}")
    return target


def _call_predicate(fn: Callable, message: dict[str, object], attributes: dict[str, object]) -> bool:
    param_count = len(inspect.signature(fn).parameters)
    if param_count <= 0:
        return bool(fn())
    if param_count == 1:
        return bool(fn(message))
    return bool(fn(message, attributes))


def _logic_condition_predicate(condition: str) -> Callable[[dict, dict[str, object]], bool]:
    text = str(condition or "").strip()
    if not text:
        raise ValueError("LogicSwitch condition must be non-empty")

    if text.startswith("python:"):
        fn = _resolve_python_binding(text)
        if fn is None:
            raise ValueError(f"Invalid LogicSwitch Python condition binding '{text}'")

        def python_predicate(message: dict, attributes: dict[str, object]) -> bool:
            return _call_predicate(fn, message, attributes)

        return python_predicate

    code = compile(text, "<aml logic condition>", "eval")

    def expression_predicate(message: dict, attributes: dict[str, object]) -> bool:
        locals_dict = {
            "attributes": attributes,
            "input": message,
            "message": message,
        }
        return bool(eval(code, _SAFE_EXPR_GLOBALS, locals_dict))

    return expression_predicate


def _parse_jsonish_object(text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise TypeError("expected a string")

    stripped = re.sub(_THINKING_BLOCK_PATTERN, "", text).strip()
    candidates: list[str] = []

    for m in re.finditer(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE):
        inner = (m.group(1) or "").strip()
        if inner:
            candidates.append(inner)

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(stripped[start : end + 1].strip())

    candidates.append(stripped)

    last_error: Exception | None = None
    for cand in candidates:
        if not cand:
            continue
        try:
            parsed = json.loads(cand)
        except Exception as exc:
            last_error = exc
            try:
                parsed = ast.literal_eval(cand)
            except Exception as exc2:
                last_error = exc2
                continue
        if isinstance(parsed, dict):
            return parsed

    raise ValueError(f"Failed to parse JSON object: {last_error}")


def _extract_inner_graph_obj(graph_design: Any) -> dict[str, Any]:
    if isinstance(graph_design, (str, Path)):
        p = Path(graph_design)
        if p.exists():
            content = p.read_text(encoding="utf-8")
            graph_design = _parse_jsonish_object(content)
        else:
            graph_design = _parse_jsonish_object(str(graph_design))

    if not isinstance(graph_design, dict):
        raise ValueError("graph_design must be a dict / JSON object / file path")

    # Unwrap common wrappers until we reach the `{nodes,edges}` shape.
    # Some prompts produce nested wrappers like `{graph_design:{graph:{nodes,edges}}}`.
    obj: Any = graph_design
    for _ in range(10):
        if isinstance(obj, dict) and isinstance(obj.get("nodes"), list) and isinstance(obj.get("edges"), list):
            return obj
        if isinstance(obj, dict) and isinstance(obj.get("graph_design"), dict):
            obj = obj["graph_design"]
            continue
        if isinstance(obj, dict) and isinstance(obj.get("graph"), dict):
            obj = obj["graph"]
            continue
        break

    raise ValueError(
        "graph_design JSON must contain `{nodes,edges}` or a wrapper like "
        "`{graph_design:{nodes,edges}}`, `{graph:{nodes,edges}}`."
    )


def _normalize_builtin(value: str, *, in_loop_subgraph: bool, is_source: bool) -> str:
    token = str(value).strip()
    upper = token.upper()

    if in_loop_subgraph:
        if upper in {_BUILTIN_ENTRY, _BUILTIN_EXIT, _LEGACY_START, _LEGACY_END}:
            raise ValueError("ENTRY/EXIT/START/END are not allowed inside Loop.sub_graph")
        if upper in {_BUILTIN_CONTROLLER, _BUILTIN_TERMINATE}:
            return upper
        return token

    # Non-loop scope: ENTRY/EXIT expected. Accept legacy START/END.
    if upper == _LEGACY_START:
        return _BUILTIN_ENTRY
    if upper == _LEGACY_END:
        return _BUILTIN_EXIT
    if upper in {_BUILTIN_ENTRY, _BUILTIN_EXIT}:
        return upper
    if upper in {_BUILTIN_CONTROLLER, _BUILTIN_TERMINATE}:
        raise ValueError("CONTROLLER/TERMINATE are only allowed inside Loop.sub_graph")
    return token


def _normalize_scope(graph_obj: Any, *, in_loop_subgraph: bool, path: str) -> dict[str, Any]:
    if not isinstance(graph_obj, dict):
        raise ValueError(f"{path}: expected an object with 'nodes' and 'edges'")

    nodes_raw = graph_obj.get("nodes")
    edges_raw = graph_obj.get("edges")
    if not isinstance(nodes_raw, list) or not isinstance(edges_raw, list):
        raise ValueError(f"{path}: must contain list 'nodes' and list 'edges'")

    node_configs: dict[str, dict[str, Any]] = {}
    builtins = (
        {_BUILTIN_CONTROLLER, _BUILTIN_TERMINATE}
        if in_loop_subgraph
        else {_BUILTIN_ENTRY, _BUILTIN_EXIT, _LEGACY_START, _LEGACY_END}
    )

    nodes: list[dict[str, Any]] = []
    for i, raw in enumerate(nodes_raw):
        if not isinstance(raw, dict):
            raise ValueError(f"{path}.nodes[{i}]: node must be an object")

        raw_name = raw.get("name", raw.get("id"))
        if not _is_non_empty_str(raw_name):
            raise ValueError(f"{path}.nodes[{i}].name: must be non-empty string")
        name = str(raw_name).strip()
        if not _NODE_NAME_PATTERN.match(name):
            raise ValueError(f"{path}.nodes[{i}].name: invalid id '{name}'")
        if name.upper() in {b.upper() for b in builtins}:
            raise ValueError(f"{path}.nodes[{i}].name: '{name}' is reserved")
        if name in node_configs:
            raise ValueError(f"{path}.nodes[{i}].name: duplicate node '{name}'")

        node_type = raw.get("type")
        if not _is_non_empty_str(node_type):
            raise ValueError(f"{path}.nodes[{i}].type: must be non-empty string")
        node_type = str(node_type).strip()
        if node_type not in _ALLOWED_TYPES:
            raise ValueError(f"{path}.nodes[{i}].type: unsupported '{node_type}'")

        label = raw.get("label")
        if not _is_non_empty_str(label):
            raise ValueError(f"{path}.nodes[{i}].label: must be non-empty string")

        node = dict(raw)
        node["name"] = name
        node["type"] = node_type
        node["label"] = str(label).strip()

        if node_type == _ACTION:
            if not _is_non_empty_str(node.get("agent")):
                raise ValueError(f"{path}.nodes[{i}].agent: required for legacy Action type")

        if node_type == _CUSTOM_NODE:
            forward = node.get("forward", node.get("binding"))
            if forward is not None and not isinstance(forward, str):
                raise ValueError(f"{path}.nodes[{i}].forward: must be string when provided")

        if "tools" not in node and "tools_allowed" in node:
            node["tools"] = node.get("tools_allowed")

        if "tools" in node:
            try:
                _str_list(node.get("tools"))
            except ValueError as exc:
                raise ValueError(f"{path}.nodes[{i}].tools: {exc}") from exc

        if node_type in {_LOOP, _SUBGRAPH}:
            sub_raw = node.get("sub_graph")
            if not isinstance(sub_raw, dict):
                if node_type == _SUBGRAPH and (
                    _is_non_empty_str(node.get("ref")) or _is_non_empty_str(node.get("implementation"))
                ):
                    sub_raw = {"nodes": [], "edges": []}
                    node["sub_graph"] = sub_raw
                else:
                    raise ValueError(f"{path}.nodes[{i}].sub_graph: required object")

            # Legacy alias for loop termination.
            if node_type == _LOOP and "terminate_condition_prompt" not in node and "terminate_condition" in node:
                node["terminate_condition_prompt"] = node.get("terminate_condition")

            node["sub_graph"] = _normalize_scope(
                sub_raw,
                in_loop_subgraph=(node_type == _LOOP),
                path=f"{path}.nodes[{i}].sub_graph",
            )

        if node_type == _LOOP:
            max_iterations = node.get("max_iterations")
            if max_iterations is not None and (not isinstance(max_iterations, int) or max_iterations <= 0):
                raise ValueError(f"{path}.nodes[{i}].max_iterations: must be positive int")
            term = node.get("terminate_condition_prompt")
            if term is not None and not isinstance(term, str):
                raise ValueError(f"{path}.nodes[{i}].terminate_condition_prompt: must be string")

        for field in ("input_fields", "output_fields"):
            if field in node:
                try:
                    _str_list(node.get(field))
                except ValueError as exc:
                    raise ValueError(f"{path}.nodes[{i}].{field}: {exc}") from exc

        # Normalize node dataflow fields.
        # - input_fields/output_fields are list[str]
        # - pull_keys/push_keys are dict[str,str] (canonical for runtime)
        if "pull_keys" not in node and "input_fields" in node:
            node["pull_keys"] = {k: "" for k in _str_list(node.get("input_fields"))}
        if "push_keys" not in node and "output_fields" in node:
            node["push_keys"] = {k: "" for k in _str_list(node.get("output_fields"))}

        for field in ("pull_keys", "push_keys"):
            if field in node and node[field] is not None:
                node[field] = _normalize_keys_dict(node[field], path=f"{path}.nodes[{i}].{field}")

        node_configs[name] = node
        nodes.append(node)

    edges: list[dict[str, Any]] = []
    for i, raw in enumerate(edges_raw):
        if not isinstance(raw, dict):
            raise ValueError(f"{path}.edges[{i}]: edge must be an object")

        src_raw = raw.get("source")
        dst_raw = raw.get("target")
        if not _is_non_empty_str(src_raw) or not _is_non_empty_str(dst_raw):
            raise ValueError(f"{path}.edges[{i}]: source/target must be non-empty strings")

        src = _normalize_builtin(str(src_raw), in_loop_subgraph=in_loop_subgraph, is_source=True)
        dst = _normalize_builtin(str(dst_raw), in_loop_subgraph=in_loop_subgraph, is_source=False)
        src = str(src).strip()
        dst = str(dst).strip()

        if in_loop_subgraph:
            src_ok = src == _BUILTIN_CONTROLLER or src in node_configs
            dst_ok = dst in {_BUILTIN_CONTROLLER, _BUILTIN_TERMINATE} or dst in node_configs
            if src == _BUILTIN_TERMINATE:
                raise ValueError(f"{path}.edges[{i}]: TERMINATE cannot be an edge source")
        else:
            src_ok = src == _BUILTIN_ENTRY or src in node_configs
            dst_ok = dst == _BUILTIN_EXIT or dst in node_configs

        if not src_ok:
            raise ValueError(f"{path}.edges[{i}]: unknown source '{src}'")
        if not dst_ok:
            raise ValueError(f"{path}.edges[{i}]: unknown target '{dst}'")

        edge = dict(raw)
        edge["source"] = src
        edge["target"] = dst
        if "condition" not in edge and _is_non_empty_str(edge.get("label")):
            edge["condition"] = str(edge.get("label")).strip()

        # Normalize edge keys:
        # - canonical: `keys` (dict[str,str])
        # - alias: `key`
        if "keys" not in edge and "key" in edge:
            edge["keys"] = edge.get("key")
        if "keys" in edge:
            edge["keys"] = _normalize_keys_dict(edge.get("keys"), path=f"{path}.edges[{i}].keys")

        # Loop controller edges must NOT carry conditions.
        if in_loop_subgraph and src == _BUILTIN_CONTROLLER and "condition" in edge:
            raise ValueError(f"{path}.edges[{i}]: CONTROLLER outgoing edges must not include 'condition'")

        source_node_config = node_configs.get(src)
        if isinstance(source_node_config, dict) and str(source_node_config.get("type", "")).strip() == _SWITCH:
            cond = edge.get("condition")
            if not _is_non_empty_str(cond):
                raise ValueError(f"{path}.edges[{i}]: switch edge '{src}->{dst}' requires condition")

        edges.append(edge)

    # Structural requirements + reachability checks
    if in_loop_subgraph:
        if not any(
            e.get("source") == _BUILTIN_CONTROLLER and str(e.get("target")) in node_configs for e in edges
        ):
            raise ValueError(f"{path}: Loop.sub_graph must contain at least one CONTROLLER -> <node> edge")
        if not any(
            e.get("target") == _BUILTIN_CONTROLLER and str(e.get("source")) in node_configs for e in edges
        ):
            raise ValueError(f"{path}: Loop.sub_graph must contain at least one <node> -> CONTROLLER edge")

        # Reachability: every node reachable from CONTROLLER
        adj: dict[str, set[str]] = {_BUILTIN_CONTROLLER: set(), _BUILTIN_TERMINATE: set()}
        for n in node_configs.keys():
            adj.setdefault(n, set())
        for e in edges:
            adj.setdefault(str(e["source"]), set()).add(str(e["target"]))

        def bfs(start: str) -> set[str]:
            seen: set[str] = set()
            stack: list[str] = [start]
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                stack.extend(list(adj.get(cur, set())))
            return seen

        reachable = bfs(_BUILTIN_CONTROLLER)
        for n in node_configs.keys():
            if n not in reachable:
                raise ValueError(f"{path}: node '{n}' is not reachable from CONTROLLER")

        # Can reach back to CONTROLLER (or TERMINATE if used)
        reverse: dict[str, set[str]] = {}
        for src, dsts in adj.items():
            for dst in dsts:
                reverse.setdefault(dst, set()).add(src)
        seeds: list[str] = [_BUILTIN_CONTROLLER]
        if any(e.get("target") == _BUILTIN_TERMINATE for e in edges):
            seeds.append(_BUILTIN_TERMINATE)
        stack = seeds[:]
        can_reach: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in can_reach:
                continue
            can_reach.add(cur)
            stack.extend(list(reverse.get(cur, set())))
        for n in node_configs.keys():
            if n not in can_reach:
                raise ValueError(f"{path}: node '{n}' cannot reach CONTROLLER/TERMINATE")
    else:
        if len(nodes) == 0:
            if len(edges) == 0 and path.endswith(".sub_graph"):
                return {"nodes": nodes, "edges": edges}
            raise ValueError(f"{path}: graph must contain at least one node")
        if not any(e.get("source") == _BUILTIN_ENTRY and str(e.get("target")) in node_configs for e in edges):
            raise ValueError(f"{path}: graph must contain at least one ENTRY -> <node> edge")
        if not any(e.get("target") == _BUILTIN_EXIT and str(e.get("source")) in node_configs for e in edges):
            raise ValueError(f"{path}: graph must contain at least one <node> -> EXIT edge")

        adj: dict[str, set[str]] = {_BUILTIN_ENTRY: set(), _BUILTIN_EXIT: set()}
        for n in node_configs.keys():
            adj.setdefault(n, set())
        for e in edges:
            adj.setdefault(str(e["source"]), set()).add(str(e["target"]))

        def bfs(start: str) -> set[str]:
            seen: set[str] = set()
            stack: list[str] = [start]
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                stack.extend(list(adj.get(cur, set())))
            return seen

        reachable = bfs(_BUILTIN_ENTRY)
        for n in node_configs.keys():
            if n not in reachable:
                raise ValueError(f"{path}: node '{n}' is not reachable from ENTRY")

        # Reverse BFS from EXIT
        reverse: dict[str, set[str]] = {}
        for src, dsts in adj.items():
            for dst in dsts:
                reverse.setdefault(dst, set()).add(src)
        stack = [_BUILTIN_EXIT]
        can_reach_exit: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in can_reach_exit:
                continue
            can_reach_exit.add(cur)
            stack.extend(list(reverse.get(cur, set())))
        for n in node_configs.keys():
            if n not in can_reach_exit:
                raise ValueError(f"{path}: node '{n}' cannot reach EXIT")

    return {"nodes": nodes, "edges": edges}


def validate_graph_design_strict(graph_design: Any) -> dict[str, Any]:
    """Validate and normalize a `graph_design` object.

    This validator accepts:
    - a dict containing `{graph_design:{nodes,edges}}` (recommended)
    - a dict containing `{graph:{nodes,edges}}` (legacy wrapper)
    - a dict containing `{nodes,edges}`
    - a file path (string/Path) containing a JSON object

    Normalization rules:
    - Accept legacy `START`/`END` in the top-level graph as aliases for `ENTRY`/`EXIT`.
    - Inside `Loop.sub_graph`, only `CONTROLLER`/`TERMINATE` are allowed as built-in endpoints.
      `ENTRY`/`EXIT` (and legacy `START`/`END`) are rejected to keep Loop semantics consistent.

    Args:
        graph_design: Input graph design object or file path.

    Returns:
        A normalized dict with keys `nodes` and `edges` for the top-level graph.

    Raises:
        ValueError: If the graph design is invalid or violates normalization constraints.
    """
    inner = _extract_inner_graph_obj(graph_design)
    return _normalize_scope(inner, in_loop_subgraph=False, path="graph_design")


def normalize_graph_design(graph_design: Any) -> dict[str, Any]:
    """Normalize a `graph_design` object.

    This is currently an alias of `validate_graph_design_strict` and will raise on invalid input.
    """
    # Fast-path: if the workflow returns a JSON string (not a file path), decode it first.
    # Do not break file-path support (e.g. cached `graph_design.json`), so this must be best-effort.
    if isinstance(graph_design, str):
        stripped = graph_design.strip()
        if stripped and stripped[0] in "{[":
            try:
                graph_design = json.loads(stripped)
            except Exception:
                pass
    return validate_graph_design_strict(graph_design)


def _build_action_kwargs(node_config: dict[str, Any], model: Model, tools_by_name: dict[str, Callable]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": str(node_config["instructions"]).strip(),
        "formatters": [ParagraphMessageFormatter(), TwinsFieldTextFormatter()],
    }

    if _is_non_empty_str(node_config.get("prompt_template")):
        kwargs["prompt_template"] = str(node_config["prompt_template"]).strip()

    tools = _str_list(node_config.get("tools")) if "tools" in node_config else []
    if tools:
        unknown = [name for name in tools if name not in tools_by_name]
        if unknown:
            raise ValueError(f"Unknown tools in node '{node_config.get('name', '')}': {unknown}")
        kwargs["tools"] = [tools_by_name[name] for name in tools]

    for key in ("max_retries", "retry_delay", "retry_backoff"):
        value = node_config.get(key)
        if value is not None:
            if not isinstance(value, int):
                raise ValueError(f"Node '{node_config.get('name', '')}' field '{key}' must be int")
            kwargs[key] = value

    for key in ("model_settings", "pull_keys", "push_keys"):
        value = node_config.get(key)
        if value is not None:
            if not isinstance(value, dict):
                raise ValueError(f"Node '{node_config.get('name', '')}' field '{key}' must be dict")
            kwargs[key] = value

    return kwargs


def _build_custom_node_kwargs(node_config: dict[str, Any], tools_by_name: dict[str, Callable]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "forward": _resolve_python_binding(node_config.get("forward", node_config.get("binding"))),
    }

    tools = _str_list(node_config.get("tools")) if "tools" in node_config else []
    if tools:
        unknown = [name for name in tools if name not in tools_by_name]
        if unknown:
            raise ValueError(f"Unknown tools in custom node '{node_config.get('name', '')}': {unknown}")
        kwargs["tools"] = [tools_by_name[name] for name in tools]

    for key in ("pull_keys", "push_keys", "attributes"):
        value = node_config.get(key)
        if value is not None:
            if not isinstance(value, dict):
                raise ValueError(f"Node '{node_config.get('name', '')}' field '{key}' must be dict")
            kwargs[key] = value

    return kwargs


def _bind_switch_conditions(bindings: dict[str, list[tuple[Any, str]]], created: dict[str, Any]) -> None:
    for switch_name, items in bindings.items():
        switch_node = created.get(switch_name)
        if isinstance(switch_node, LogicSwitch):
            for edge_obj, condition in items:
                switch_node.condition_binding(_logic_condition_predicate(condition), edge_obj)
            continue
        if not isinstance(switch_node, AgentSwitch):
            raise ValueError(f"Node '{switch_name}' is not a supported switch")
        for edge_obj, condition in items:
            switch_node.condition_binding(condition, edge_obj)


def _aml_node_config(node: AmlNode) -> dict[str, Any]:
    config: dict[str, Any] = {
        "name": node.id,
        "label": node.label or node.id,
    }
    if node.pull_keys is not None:
        config["pull_keys"] = dict(node.pull_keys)
    if node.push_keys is not None:
        config["push_keys"] = dict(node.push_keys)
    if node.attributes is not None:
        config["attributes"] = dict(node.attributes)

    if node.kind == "agent":
        config.update(
            {
                "type": _ACTION,
                "agent": node.agent_ref or node.id,
                "instructions": node.instructions or f"Execute AML agent node '{node.id}'.",
            }
        )
        if node.prompt_template:
            config["prompt_template"] = node.prompt_template
        return config

    if node.kind == "custom_node":
        config["type"] = _CUSTOM_NODE
        if node.forward:
            config["forward"] = node.forward
        return config

    if node.kind in {"logic_switch", "agent_switch"}:
        config["type"] = _SWITCH
        config["switch_kind"] = node.kind
        return config

    if node.kind == "loop":
        config.update(
            {
                "type": _LOOP,
                "max_iterations": node.max_iterations or 3,
            }
        )
        if node.terminate_condition_prompt:
            config["terminate_condition_prompt"] = node.terminate_condition_prompt
        if node.terminate_condition_expr:
            config["terminate_condition_expr"] = node.terminate_condition_expr
        return config

    if node.kind == "graph":
        config["type"] = _SUBGRAPH
        if node.ref:
            config["ref"] = node.ref
        if node.implementation:
            config["implementation"] = node.implementation
        return config

    raise ValueError(f"Unsupported AML node kind '{node.kind}' for node '{node.id}'")


def _compile_aml_graph(graph: Graph, aml_graph: AmlGraph, model: Model, tools: list[Callable] | None) -> None:
    node_configs = {node.id: _aml_node_config(node) for node in aml_graph.nodes}
    nodes_by_id = {node.id: node for node in aml_graph.nodes}
    tools_by_name = _tool_map(tools)
    created: dict[str, Any] = {}

    for node in aml_graph.nodes:
        name = node.id
        node_config = node_configs[name]
        node_type = str(node_config.get("type", "")).strip()
        if node_type == _ACTION:
            created[name] = graph.create_node(
                Agent,
                name=name,
                **_build_action_kwargs(node_config, model, tools_by_name),
            )
        elif node_type == _CUSTOM_NODE:
            created[name] = graph.create_node(
                CustomNode,
                name=name,
                **_build_custom_node_kwargs(node_config, tools_by_name),
            )
        elif node_type == _SWITCH:
            if str(node_config.get("switch_kind") or "").strip() == "logic_switch":
                created[name] = graph.create_node(
                    LogicSwitch,
                    name=name,
                    pull_keys=node_config.get("pull_keys"),
                    push_keys=node_config.get("push_keys"),
                    attributes=node_config.get("attributes"),
                )
            else:
                created[name] = graph.create_node(
                    AgentSwitch,
                    name=name,
                    model=model,
                    pull_keys=node_config.get("pull_keys"),
                    push_keys=node_config.get("push_keys"),
                    attributes=node_config.get("attributes"),
                )
        elif node_type == _SUBGRAPH:
            sub = graph.create_node(
                Graph,
                name=name,
                pull_keys=node_config.get("pull_keys"),
                push_keys=node_config.get("push_keys"),
                attributes=node_config.get("attributes"),
            )
            created[name] = sub
            if node.sub_graph is not None:
                _compile_aml_graph(sub, node.sub_graph, model, tools)
        elif node_type == _LOOP:
            max_it = node_config.get("max_iterations") if isinstance(node_config.get("max_iterations"), int) else 3
            term = node_config.get("terminate_condition_prompt")
            term_prompt = term.strip() if isinstance(term, str) else ""
            term_expr = node_config.get("terminate_condition_expr")
            term_function = (
                _logic_condition_predicate(term_expr)
                if isinstance(term_expr, str) and term_expr.strip()
                else None
            )
            loop = graph.create_node(
                Loop,
                name=name,
                max_iterations=max_it if max_it and max_it > 0 else 3,
                model=model if term_prompt else None,
                terminate_condition_prompt=term_prompt or None,
                terminate_condition_function=term_function,
                pull_keys=node_config.get("pull_keys"),
                push_keys=node_config.get("push_keys"),
                attributes=node_config.get("attributes"),
            )
            created[name] = loop
            if node.sub_graph is None:
                raise ValueError(f"AML loop node '{name}' is missing a sub_graph")
            _compile_aml_loop(loop, node.sub_graph, model, tools)
        else:
            raise ValueError(f"Unsupported AML node type '{node_type}' for node '{name}'")

    bindings: dict[str, list[tuple[Any, str]]] = {}
    for edge in aml_graph.edges:
        src = edge.source.strip()
        dst = edge.target.strip()
        keys = edge.keys or {}
        if not isinstance(keys, dict):
            raise ValueError(f"AML edge '{src}->{dst}' field 'keys' must be dict")

        if src == _BUILTIN_ENTRY:
            receiver = graph._exit if dst == _BUILTIN_EXIT else created[dst]
            edge_obj = graph.edge_from_entry(receiver, keys=keys)
        elif dst == _BUILTIN_EXIT:
            sender = graph._entry if src == _BUILTIN_ENTRY else created[src]
            edge_obj = graph.edge_to_exit(sender, keys=keys)
        else:
            edge_obj = graph.create_edge(created[src], created[dst], keys=keys)

        source_node = nodes_by_id.get(src)
        if source_node is not None and source_node.kind in {"logic_switch", "agent_switch"}:
            bindings.setdefault(src, []).append((edge_obj, str(edge.condition or "").strip()))

    _bind_switch_conditions(bindings, created)


def _compile_aml_loop(loop: Loop, aml_graph: AmlGraph, model: Model, tools: list[Callable] | None) -> None:
    node_configs = {node.id: _aml_node_config(node) for node in aml_graph.nodes}
    nodes_by_id = {node.id: node for node in aml_graph.nodes}
    tools_by_name = _tool_map(tools)
    created: dict[str, Any] = {}

    for node in aml_graph.nodes:
        name = node.id
        node_config = node_configs[name]
        node_type = str(node_config.get("type", "")).strip()
        if node_type == _ACTION:
            created[name] = loop.create_node(
                Agent,
                name=name,
                **_build_action_kwargs(node_config, model, tools_by_name),
            )
        elif node_type == _CUSTOM_NODE:
            created[name] = loop.create_node(
                CustomNode,
                name=name,
                **_build_custom_node_kwargs(node_config, tools_by_name),
            )
        elif node_type == _SWITCH:
            if str(node_config.get("switch_kind") or "").strip() == "logic_switch":
                created[name] = loop.create_node(
                    LogicSwitch,
                    name=name,
                    pull_keys=node_config.get("pull_keys"),
                    push_keys=node_config.get("push_keys"),
                    attributes=node_config.get("attributes"),
                )
            else:
                created[name] = loop.create_node(
                    AgentSwitch,
                    name=name,
                    model=model,
                    pull_keys=node_config.get("pull_keys"),
                    push_keys=node_config.get("push_keys"),
                    attributes=node_config.get("attributes"),
                )
        elif node_type == _SUBGRAPH:
            sub = loop.create_node(
                Graph,
                name=name,
                pull_keys=node_config.get("pull_keys"),
                push_keys=node_config.get("push_keys"),
                attributes=node_config.get("attributes"),
            )
            created[name] = sub
            if node.sub_graph is not None:
                _compile_aml_graph(sub, node.sub_graph, model, tools)
        elif node_type == _LOOP:
            max_it = node_config.get("max_iterations") if isinstance(node_config.get("max_iterations"), int) else 3
            term = node_config.get("terminate_condition_prompt")
            term_prompt = term.strip() if isinstance(term, str) else ""
            term_expr = node_config.get("terminate_condition_expr")
            term_function = (
                _logic_condition_predicate(term_expr)
                if isinstance(term_expr, str) and term_expr.strip()
                else None
            )
            nested_loop = loop.create_node(
                Loop,
                name=name,
                max_iterations=max_it if max_it and max_it > 0 else 3,
                model=model if term_prompt else None,
                terminate_condition_prompt=term_prompt or None,
                terminate_condition_function=term_function,
                pull_keys=node_config.get("pull_keys"),
                push_keys=node_config.get("push_keys"),
                attributes=node_config.get("attributes"),
            )
            created[name] = nested_loop
            if node.sub_graph is None:
                raise ValueError(f"AML loop node '{name}' is missing a sub_graph")
            _compile_aml_loop(nested_loop, node.sub_graph, model, tools)
        else:
            raise ValueError(f"Unsupported AML node type '{node_type}' inside loop for node '{name}'")

    bindings: dict[str, list[tuple[Any, str]]] = {}
    for edge in aml_graph.edges:
        src = edge.source.strip()
        dst = edge.target.strip()
        keys = edge.keys or {}
        if not isinstance(keys, dict):
            raise ValueError(f"AML edge '{src}->{dst}' field 'keys' must be dict")

        if src == _BUILTIN_CONTROLLER:
            if dst == _BUILTIN_CONTROLLER:
                raise ValueError("Loop edge CONTROLLER -> CONTROLLER is not allowed")
            if dst == _BUILTIN_TERMINATE:
                edge_obj = loop.edge_to_terminate_node(loop._controller, keys=keys)  # type: ignore[attr-defined]
            else:
                edge_obj = loop.edge_from_controller(created[dst], keys=keys)
        elif dst == _BUILTIN_CONTROLLER:
            edge_obj = loop.edge_to_controller(created[src], keys=keys)
        elif dst == _BUILTIN_TERMINATE:
            edge_obj = loop.edge_to_terminate_node(created[src], keys=keys)
        else:
            edge_obj = loop.create_edge(created[src], created[dst], keys=keys)

        source_node = nodes_by_id.get(src)
        if source_node is not None and source_node.kind in {"logic_switch", "agent_switch"}:
            bindings.setdefault(src, []).append((edge_obj, str(edge.condition or "").strip()))

    _bind_switch_conditions(bindings, created)


def _compile_aml_document(
    target_graph: Graph,
    document: AmlDocument,
    model: Model,
    tools: list[Callable] | None,
) -> None:
    validate_aml_document(document)
    _compile_aml_graph(target_graph, document.root_graph, model, tools)


def _compile_graph(graph: Graph, graph_obj: dict[str, Any], model: Model, tools: list[Callable] | None) -> None:
    node_configs = {str(n["name"]).strip(): n for n in graph_obj["nodes"] if isinstance(n, dict)}
    tools_by_name = _tool_map(tools)
    created: dict[str, Any] = {}

    for name, node_config in node_configs.items():
        node_type = str(node_config.get("type", "")).strip()
        if node_type == _ACTION:
            if not _is_non_empty_str(node_config.get("instructions")):
                raise ValueError(f"Node '{name}' uses the legacy Action type but is missing non-empty 'instructions'")
            created[name] = graph.create_node(
                Agent, name=name, **_build_action_kwargs(node_config, model, tools_by_name)
            )
        elif node_type == _CUSTOM_NODE:
            created[name] = graph.create_node(
                CustomNode, name=name, **_build_custom_node_kwargs(node_config, tools_by_name)
            )
        elif node_type == _SWITCH:
            if str(node_config.get("switch_kind") or "").strip() == "logic_switch":
                created[name] = graph.create_node(
                    LogicSwitch,
                    name=name,
                    pull_keys=node_config.get("pull_keys"),
                    push_keys=node_config.get("push_keys"),
                )
            else:
                created[name] = graph.create_node(
                    AgentSwitch,
                    name=name,
                    model=model,
                    pull_keys=node_config.get("pull_keys"),
                    push_keys=node_config.get("push_keys"),
                )
        elif node_type == _SUBGRAPH:
            sub = graph.create_node(
                Graph,
                name=name,
                pull_keys=node_config.get("pull_keys"),
                push_keys=node_config.get("push_keys"),
            )
            created[name] = sub
            _compile_graph(sub, normalize_graph_design(node_config["sub_graph"]), model, tools)
        elif node_type == _LOOP:
            max_it = node_config.get("max_iterations") if isinstance(node_config.get("max_iterations"), int) else 3
            term = node_config.get("terminate_condition_prompt")
            term_prompt = term.strip() if isinstance(term, str) else ""
            loop = graph.create_node(
                Loop,
                name=name,
                max_iterations=max_it if max_it and max_it > 0 else 3,
                model=model if term_prompt else None,
                terminate_condition_prompt=term_prompt or None,
                pull_keys=node_config.get("pull_keys"),
                push_keys=node_config.get("push_keys"),
            )
            created[name] = loop
            _compile_loop(
                loop,
                _normalize_scope(
                    node_config["sub_graph"],
                    in_loop_subgraph=True,
                    path=f"graph_design.nodes[{name}].sub_graph",
                ),
                model,
                tools,
            )
        else:
            raise ValueError(f"Unsupported node type '{node_type}' for node '{name}'")

    bindings: dict[str, list[tuple[Any, str]]] = {}
    for edge in graph_obj["edges"]:
        src = str(edge["source"]).strip()
        dst = str(edge["target"]).strip()
        keys = edge.get("keys") if "keys" in edge else {}
        if keys is None:
            keys = {}
        if not isinstance(keys, dict):
            raise ValueError(f"Edge '{src}->{dst}' field 'keys' must be dict")

        if src == _BUILTIN_ENTRY:
            receiver = graph._exit if dst == _BUILTIN_EXIT else created[dst]
            edge_obj = graph.edge_from_entry(receiver, keys=keys)
        elif dst == _BUILTIN_EXIT:
            sender = graph._entry if src == _BUILTIN_ENTRY else created[src]
            edge_obj = graph.edge_to_exit(sender, keys=keys)
        else:
            edge_obj = graph.create_edge(created[src], created[dst], keys=keys)

        source_node_config = node_configs.get(src)
        if isinstance(source_node_config, dict) and str(source_node_config.get("type", "")).strip() == _SWITCH:
            cond = str(edge.get("condition", "")).strip()
            bindings.setdefault(src, []).append((edge_obj, cond))

    _bind_switch_conditions(bindings, created)


def _compile_loop(loop: Loop, sub_graph_obj: dict[str, Any], model: Model, tools: list[Callable] | None) -> None:
    node_configs = {str(n["name"]).strip(): n for n in sub_graph_obj["nodes"] if isinstance(n, dict)}
    tools_by_name = _tool_map(tools)
    created: dict[str, Any] = {}

    for name, node_config in node_configs.items():
        node_type = str(node_config.get("type", "")).strip()
        if node_type == _ACTION:
            if not _is_non_empty_str(node_config.get("instructions")):
                raise ValueError(f"Node '{name}' uses the legacy Action type but is missing non-empty 'instructions'")
            created[name] = loop.create_node(
                Agent, name=name, **_build_action_kwargs(node_config, model, tools_by_name)
            )
        elif node_type == _CUSTOM_NODE:
            created[name] = loop.create_node(
                CustomNode, name=name, **_build_custom_node_kwargs(node_config, tools_by_name)
            )
        elif node_type == _SWITCH:
            if str(node_config.get("switch_kind") or "").strip() == "logic_switch":
                created[name] = loop.create_node(
                    LogicSwitch,
                    name=name,
                    pull_keys=node_config.get("pull_keys"),
                    push_keys=node_config.get("push_keys"),
                )
            else:
                created[name] = loop.create_node(
                    AgentSwitch,
                    name=name,
                    model=model,
                    pull_keys=node_config.get("pull_keys"),
                    push_keys=node_config.get("push_keys"),
                )
        elif node_type == _SUBGRAPH:
            sub = loop.create_node(
                Graph,
                name=name,
                pull_keys=node_config.get("pull_keys"),
                push_keys=node_config.get("push_keys"),
            )
            created[name] = sub
            _compile_graph(sub, normalize_graph_design(node_config["sub_graph"]), model, tools)
        elif node_type == _LOOP:
            max_it = node_config.get("max_iterations") if isinstance(node_config.get("max_iterations"), int) else 3
            term = node_config.get("terminate_condition_prompt")
            term_prompt = term.strip() if isinstance(term, str) else ""
            nested_loop = loop.create_node(
                Loop,
                name=name,
                max_iterations=max_it if max_it and max_it > 0 else 3,
                model=model if term_prompt else None,
                terminate_condition_prompt=term_prompt or None,
                pull_keys=node_config.get("pull_keys"),
                push_keys=node_config.get("push_keys"),
            )
            created[name] = nested_loop
            _compile_loop(
                nested_loop,
                _normalize_scope(
                    node_config["sub_graph"],
                    in_loop_subgraph=True,
                    path=f"graph_design.nodes[{loop.name}].sub_graph.nodes[{name}].sub_graph",
                ),
                model,
                tools,
            )
        else:
            raise ValueError(f"Unsupported node type '{node_type}' inside Loop.sub_graph for node '{name}'")

    bindings: dict[str, list[tuple[Any, str]]] = {}
    for edge in sub_graph_obj["edges"]:
        src = str(edge["source"]).strip()
        dst = str(edge["target"]).strip()
        keys = edge.get("keys") if "keys" in edge else {}
        if keys is None:
            keys = {}
        if not isinstance(keys, dict):
            raise ValueError(f"Edge '{src}->{dst}' field 'keys' must be dict")

        if src == _BUILTIN_CONTROLLER:
            if dst == _BUILTIN_CONTROLLER:
                raise ValueError("Loop edge CONTROLLER -> CONTROLLER is not allowed")
            if dst == _BUILTIN_TERMINATE:
                edge_obj = loop.edge_to_terminate_node(loop._controller, keys=keys)  # type: ignore[attr-defined]
            else:
                edge_obj = loop.edge_from_controller(created[dst], keys=keys)
        elif dst == _BUILTIN_CONTROLLER:
            edge_obj = loop.edge_to_controller(created[src], keys=keys)
        elif dst == _BUILTIN_TERMINATE:
            edge_obj = loop.edge_to_terminate_node(created[src], keys=keys)
        else:
            edge_obj = loop.create_edge(created[src], created[dst], keys=keys)

        source_node_config = node_configs.get(src)
        if isinstance(source_node_config, dict) and str(source_node_config.get("type", "")).strip() == _SWITCH:
            cond = str(edge.get("condition", "")).strip()
            bindings.setdefault(src, []).append((edge_obj, cond))

    _bind_switch_conditions(bindings, created)


def compile_graph_design(
    *,
    target_graph: Graph,
    graph_design: dict[str, Any],
    model: Model,
    tools: list[Callable] | None = None,
) -> None:
    """Compile a `graph_design` JSON into an in-memory MASFactory `Graph`.

    The compiler:
    - Validates and normalizes the input `graph_design`
    - Creates nodes from legacy Action/Switch/Loop/Subgraph records on `target_graph`
    - Creates edges based on `edges` specifications

    Built-in endpoints:
    - Top-level graph: `ENTRY`/`EXIT` (legacy `START`/`END` are accepted)
    - Loop sub-graph: `CONTROLLER`/`TERMINATE`

    Args:
        target_graph: The graph instance to populate (mutated in-place).
        graph_design: Graph design JSON object already loaded in memory.
            Accepted shapes:
            - `{ "graph_design": { "nodes": [...], "edges": [...] } }`
            - `{ "graph": { "nodes": [...], "edges": [...] } }` (legacy wrapper)
            - `{ "nodes": [...], "edges": [...] }` (inner object)
            Use `load_cached_graph_design()` to load from a file path.
        model: Model adapter injected into legacy Action records.
        tools: Optional tool registry. When provided, legacy Action `tools` names are resolved
            against this list by `__name__`.

    Raises:
        ValueError: If the design is invalid or contains unsupported node/edge specs.
    """
    if not isinstance(graph_design, dict):
        raise TypeError(
            "compile_graph_design expects an in-memory graph_design object (dict). "
            "If you have a file path, call load_cached_graph_design(path) first."
        )
    graph_obj = normalize_graph_design(graph_design)
    _compile_graph(target_graph, graph_obj, model, tools)


def compile_aml(
    *,
    target_graph: Graph,
    aml: str | Path,
    model: Model,
    tools: list[Callable] | None = None,
) -> None:
    """Compile AML directly into an in-memory MASFactory ``Graph``."""
    document = parse_aml_document(aml, strict=True)
    _compile_aml_document(target_graph, document, model, tools)


def load_cached_graph_design(cache_path: str | Path) -> dict[str, Any]:
    """Load a cached graph_design JSON or AML file.

    Accepts either:
    - file path to JSON / AML
    - directory path containing graph_design.json
    """
    path = Path(cache_path)
    if path.is_dir():
        path = path / "graph_design.json"
    if not path.exists():
        raise FileNotFoundError(str(path))

    if path.suffix.lower() == ".aml":
        return normalize_graph_design(aml_to_graph_design(path, strict=True))

    obj = _parse_jsonish_object(path.read_text(encoding="utf-8"))
    return normalize_graph_design(obj)


def load_cached_aml(cache_path: str | Path) -> str | Path:
    """Load a cached AML file, migrating legacy graph_design JSON at the boundary."""
    path = Path(cache_path)
    if path.is_dir():
        aml_path = path / "graph.aml"
        if aml_path.exists():
            return aml_path
        path = path / "graph_design.json"
    if not path.exists():
        raise FileNotFoundError(str(path))

    if path.suffix.lower() == ".aml":
        return path

    obj = _parse_jsonish_object(path.read_text(encoding="utf-8"))
    graph_obj = normalize_graph_design(obj)
    return graph_design_to_aml_document(
        graph_obj,
        document_id=f"{path.stem}.legacy_cache",
        root_graph_id=path.stem.replace(".", "_") or "root",
        source="legacy_graph_design_cache",
    )


__all__ = [
    "compile_graph_design",
    "compile_aml",
    "load_cached_aml",
    "load_cached_graph_design",
    "normalize_graph_design",
    "validate_graph_design_strict",
]
