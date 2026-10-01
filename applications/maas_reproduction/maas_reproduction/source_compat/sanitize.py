"""Source MaAS/EvalPlus code extraction semantics.

The primary implementation is a direct local port of
``MaAS-main/maas/utils/sanitize.py``. Its parser dependencies are included in
the reproduction lock file. An AST fallback keeps lightweight test
environments usable when those parser wheels are absent.
"""
from __future__ import annotations

import ast
from collections import deque
from typing import Any, Optional


def syntax_check(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except (SyntaxError, MemoryError):
        return False


def code_extract(text: str) -> str:
    lines = str(text).split("\n")
    longest_line_pair = (0, 0)
    longest_so_far = 0
    for start in range(len(lines)):
        for end in range(start + 1, len(lines)):
            current = "\n".join(lines[start : end + 1])
            if syntax_check(current):
                length = sum(1 for line in lines[start : end + 1] if line.strip())
                if length > longest_so_far:
                    longest_so_far = length
                    longest_line_pair = (start, end)
    return "\n".join(lines[longest_line_pair[0] : longest_line_pair[1] + 1])


def _tree_sitter_sanitize(code: str, entrypoint: Optional[str]) -> str:
    import tree_sitter_python
    from tree_sitter import Language, Parser

    extracted = code_extract(code)
    code_bytes = bytes(extracted, "utf8")
    tree = Parser(Language(tree_sitter_python.language())).parse(code_bytes)

    def traverse(node: Any):
        cursor = node.walk()
        depth = 0
        visited_children = False
        while True:
            if not visited_children:
                yield cursor.node
                if not cursor.goto_first_child():
                    depth += 1
                    visited_children = True
            elif cursor.goto_next_sibling():
                visited_children = False
            elif not cursor.goto_parent() or depth == 0:
                break
            else:
                depth -= 1

    def definition_name(node: Any) -> str | None:
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf8")
        return None

    def has_return(node: Any) -> bool:
        return any(item.type == "return_statement" for item in traverse(node))

    imports = []
    definitions = []
    known: set[str] = set()
    for child in tree.root_node.children:
        node = child
        if child.type in ("import_statement", "import_from_statement"):
            imports.append(child)
            continue
        if child.type == "expression_statement" and child.children:
            if child.children[0].type != "assignment":
                continue
            node = child.children[0]
        elif child.type == "function_definition":
            if not has_return(child):
                continue
        elif child.type != "class_definition":
            continue
        name = definition_name(node)
        if name is not None and name not in known:
            definitions.append((name, node))
            known.add(name)

    reachable = set(known)
    if entrypoint:
        dependencies: dict[str, set[str]] = {}
        for name, node in definitions:
            dependencies[name] = {
                item.text.decode("utf8")
                for item in traverse(node)
                if item.type == "identifier"
            }
        reachable = {entrypoint}
        pending = deque((entrypoint,))
        while pending:
            current = pending.popleft()
            for dependency in dependencies.get(current, ()):
                if dependency not in reachable:
                    reachable.add(dependency)
                    pending.append(dependency)

    selected = [*imports, *(node for name, node in definitions if name in reachable)]
    output = b"".join(code_bytes[node.start_byte : node.end_byte] + b"\n" for node in selected)
    return output[:-1].decode("utf8")


def _ast_sanitize(code: str, entrypoint: Optional[str]) -> str:
    extracted = code_extract(code)
    tree = ast.parse(extracted)
    imports: list[ast.AST] = []
    definitions: list[tuple[str, ast.AST]] = []
    known: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not any(isinstance(child, ast.Return) for child in ast.walk(node)):
                continue
            name = node.name
        elif isinstance(node, ast.ClassDef):
            name = node.name
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        else:
            continue
        if name not in known:
            definitions.append((name, node))
            known.add(name)
    reachable = set(known)
    if entrypoint:
        dependencies = {
            name: {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
            for name, node in definitions
        }
        reachable = {entrypoint}
        pending = deque((entrypoint,))
        while pending:
            current = pending.popleft()
            for dependency in dependencies.get(current, ()):
                if dependency not in reachable:
                    reachable.add(dependency)
                    pending.append(dependency)
    selected = [*imports, *(node for name, node in definitions if name in reachable)]
    return "\n".join(
        fragment for node in selected if (fragment := ast.get_source_segment(extracted, node))
    )


def sanitize(code: str, entrypoint: Optional[str] = None) -> str:
    try:
        return _tree_sitter_sanitize(str(code), entrypoint)
    except ImportError:
        return _ast_sanitize(str(code), entrypoint)


__all__ = ["code_extract", "sanitize", "syntax_check"]
