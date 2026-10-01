"""Small build-time check for explicit attribute boundaries."""

from __future__ import annotations

from typing import Iterator


def iter_owned_nodes(node: object) -> Iterator[object]:
    yield node
    for child in getattr(node, "_nodes", {}).values():
        yield from iter_owned_nodes(child)
    for internal_name in ("_controller", "_terminate_node"):
        internal = getattr(node, internal_name, None)
        if internal is not None:
            yield internal


def seal_loop_attributes(loop: object) -> None:
    for internal_name in ("_controller", "_terminate_node"):
        internal = getattr(loop, internal_name, None)
        if internal is not None:
            internal.set_pull_keys({})
            internal.set_push_keys({})


def assert_explicit_attribute_policies(graph: object) -> None:
    offenders = []
    for node in iter_owned_nodes(graph):
        if getattr(node, "pull_keys", {}) is None:
            offenders.append(f"{getattr(node, 'name', type(node).__name__)}: pull_keys=None")
        if getattr(node, "push_keys", {}) is None:
            offenders.append(f"{getattr(node, 'name', type(node).__name__)}: push_keys=None")
    if offenders:
        raise AssertionError("implicit attribute inheritance in protected graph: " + "; ".join(offenders))


__all__ = ["assert_explicit_attribute_policies", "iter_owned_nodes", "seal_loop_attributes"]
