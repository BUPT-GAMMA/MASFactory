import ast
import json
import re
from typing import Any
from typing import Callable
from masfactory import Node


_ROLE_LINE_RE = re.compile(r"^\s*(?:\d+[\.\)]|[-*])\s*(.+?)\s*$")


def parse_role_descriptions(raw_roles: Any) -> list[str]:
    """Parse role descriptions from role-assigner output.

    Supports numbered/bulleted text lists and JSON/Python-literal payloads.
    Falls back to extracting quoted strings from partially broken JSON.

    Args:
        raw_roles: Output payload from the role assigner.

    Returns:
        A list of role description strings.
    """

    def _clean_role(s: str) -> str:
        return str(s).strip().strip("\u2022").strip()

    def _strip_fences(text: str) -> str:
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
        return stripped

    def _try_parse_literal(text: str) -> Any | None:
        stripped = _strip_fences(text)
        if not stripped:
            return None
        candidates: list[str] = []
        if "{" in stripped and "}" in stripped:
            candidates.append(stripped[stripped.find("{") : stripped.rfind("}") + 1])
        if "[" in stripped and "]" in stripped:
            candidates.append(stripped[stripped.find("[") : stripped.rfind("]") + 1])
        candidates.append(stripped)
        for cand in candidates:
            if not cand:
                continue
            try:
                return json.loads(cand)
            except Exception:
                try:
                    return ast.literal_eval(cand)
                except Exception:
                    continue
        return None

    def _parse_from_text(text: str) -> list[str]:
        stripped = text.strip()
        if not stripped:
            return []

        parsed = _try_parse_literal(stripped)
        if isinstance(parsed, dict):
            if "roles" in parsed:
                return parse_role_descriptions(parsed.get("roles"))
        elif isinstance(parsed, list):
            return [r for r in (_clean_role(x) for x in parsed) if r]

        # If the output looks like JSON (but is broken), prefer extracting quoted items.
        jsonish = bool(re.search(r'["\']roles["\']\s*:', stripped)) or stripped.lstrip().startswith("{")
        if jsonish:
            quoted = re.findall(r'"([^"]+)"', stripped)
            if not quoted:
                quoted = re.findall(r"'([^']+)'", stripped)
            quoted = [q for q in (_clean_role(q) for q in quoted) if q and q.lower() != "roles"]
            if quoted:
                return quoted

        # Line-based parsing (preferred, matches original AgentVerse RoleAssignerParser).
        lines = [ln.rstrip() for ln in stripped.splitlines() if ln.strip()]
        roles: list[str] = []
        current_idx: int | None = None
        for ln in lines:
            m = _ROLE_LINE_RE.match(ln)
            if m:
                role = _clean_role(m.group(1))
                if role:
                    roles.append(role)
                    current_idx = len(roles) - 1
                continue
            # Continuation line for wrapped roles.
            if current_idx is not None and (ln.startswith(" ") or ln.startswith("\t")):
                roles[current_idx] = _clean_role(roles[current_idx] + " " + ln.strip())
                continue
            role = _clean_role(ln)
            if role:
                roles.append(role)
                current_idx = len(roles) - 1

        if roles:
            return roles

        # Fallback: extract any fully-quoted strings from broken JSON.
        quoted = re.findall(r'"([^"]+)"', stripped)
        if not quoted:
            quoted = re.findall(r"'([^']+)'", stripped)
        quoted = [q for q in (_clean_role(q) for q in quoted) if q and q.lower() != "roles"]
        return quoted

    if raw_roles is None:
        return []

    if isinstance(raw_roles, dict):
        if "roles" in raw_roles:
            return parse_role_descriptions(raw_roles.get("roles"))
        return [r for r in (_clean_role(v) for v in raw_roles.values()) if r]

    if isinstance(raw_roles, (list, tuple, set)):
        roles: list[str] = []
        for item in raw_roles:
            if item is None:
                continue
            if isinstance(item, str):
                roles.extend(_parse_from_text(item))
            else:
                roles.extend(parse_role_descriptions(item))
        return [r for r in (_clean_role(r) for r in roles) if r]

    if isinstance(raw_roles, str):
        return _parse_from_text(raw_roles)

    return _parse_from_text(str(raw_roles))

def process_evaluation(node:Node,output:dict,input:dict) -> dict:
    """Post-process evaluator output and update node attributes.

    Sets `score`, `advice`, and `success` on `node.attributes`.

    Success rule:
    - If `success_threshold <= 1`: treat `score` as boolean (scalar or list) and require all to be truthy.
    - If `success_threshold > 1`: require `score >= success_threshold` (scalar or all dims in list).
    """
    score = output.get("score", 0)
    advice = output.get("advice", "No advice")

    def _coerce_number(v):
        if isinstance(v, (int, float, bool)):
            return int(v) if isinstance(v, bool) else v
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                try:
                    return float(v)
                except ValueError:
                    return 0
        return 0

    # Normalize score types:
    # - int/float/bool: keep numeric
    # - str: parse to int/float
    # - list/tuple: parse each element
    if isinstance(score, (list, tuple)):
        normalized_score = [_coerce_number(s) for s in score]
    else:
        normalized_score = _coerce_number(score)

    node.attributes["score"] = normalized_score
    node.attributes["advice"] = advice

    success_threshold = _coerce_number(node.attributes.get("success_threshold", 1))
    if success_threshold <= 1:
        # Binary mode (e.g., HumanEval / correctness)
        if isinstance(normalized_score, (list, tuple)):
            node.attributes["success"] = all(bool(s) for s in normalized_score)
        else:
            node.attributes["success"] = bool(normalized_score)
    else:
        # Multi-dimension mode: accept if all dims >= threshold, or scalar >= threshold
        if isinstance(normalized_score, (list, tuple)):
            node.attributes["success"] = all(s >= success_threshold for s in normalized_score)
        else:
            node.attributes["success"] = normalized_score >= success_threshold
    
    return input

def role_extractor(index: int) -> Callable:
    """Build a hook that injects a role description into agent input.

    Args:
        index: Role-list index to pick (0-based). In common setups, roles[0] is
            reserved for the solver, so critics start from index 1.

    Returns:
        A hook function for `Node.Hook.FORWARD.BEFORE` that sets `role_description`.
    """
    def _role_extractor(node, input) -> dict:
        roles = parse_role_descriptions(node.attributes.get("roles", []))
        
        # Pick the role at `index`, falling back to a generic expert label.
        if index < len(roles):
            role_description = roles[index]
        else:
            role_description = f"Expert {index + 1}"
        
        input["role_description"] = role_description
        return input
    return _role_extractor
