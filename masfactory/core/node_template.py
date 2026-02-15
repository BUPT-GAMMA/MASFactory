import copy
import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Generic, Type, TypeVar
from masfactory.core.node import Node
from masfactory.utils.path_filter import PathFilter, match_path_filter, parse_path_filter
from masfactory.utils.selector import SelectionTarget, Selector, build_selector


T = TypeVar("T")


@dataclass(frozen=True)
class Shared(Generic[T]):
    """
    Marker wrapper for NodeTemplate configs.

    Use this to explicitly share one dependency instance across node instances.
    """

    value: T


@dataclass(frozen=True)
class Factory(Generic[T]):
    """
    Marker wrapper for NodeTemplate configs.

    Use this to create a fresh object per NodeTemplate instantiation.
    """

    make: Callable[[], T]


_IMMUTABLE_SCALARS = (str, int, float, bool, bytes, type(None))


_TEMPLATE_DEFAULTS_CVAR: ContextVar[dict[str, Any]] = ContextVar(
    "masfactory_node_template_defaults",
    default={},
)
_TEMPLATE_OVERRIDES_CVAR: ContextVar[dict[str, Any]] = ContextVar(
    "masfactory_node_template_overrides",
    default={},
)

_TEMPLATE_DEFAULTS_RULES_CVAR: ContextVar[
    tuple[tuple[Selector, PathFilter | None, dict[str, Any]], ...]
] = ContextVar(
    "masfactory_node_template_defaults_rules",
    default=(),
)
_TEMPLATE_OVERRIDES_RULES_CVAR: ContextVar[
    tuple[tuple[Selector, PathFilter | None, dict[str, Any]], ...]
] = ContextVar(
    "masfactory_node_template_overrides_rules",
    default=(),
)


@contextmanager
def template_defaults(**defaults: Any):
    """Provide lowest-priority default kwargs for NodeTemplate materialization.

    These values are applied only when a given kwarg is missing from the final per-node config.
    Intended for "fill missing" behavior when configuring many templates at once.
    """
    previous = _TEMPLATE_DEFAULTS_CVAR.get()
    merged = {**previous, **defaults}
    token = _TEMPLATE_DEFAULTS_CVAR.set(merged)
    try:
        yield
    finally:
        _TEMPLATE_DEFAULTS_CVAR.reset(token)


@contextmanager
def template_overrides(**overrides: Any):
    """Provide highest-priority override kwargs for NodeTemplate materialization.

    These values override any existing per-node config, including explicit NodeTemplate kwargs.
    Intended for "force" behavior when you need to override many templates at once.
    """
    previous = _TEMPLATE_OVERRIDES_CVAR.get()
    merged = {**previous, **overrides}
    token = _TEMPLATE_OVERRIDES_CVAR.set(merged)
    try:
        yield
    finally:
        _TEMPLATE_OVERRIDES_CVAR.reset(token)


@contextmanager
def template_defaults_for(
    *,
    selector: Selector | None = None,
    path_filter: str | None = None,
    type_filter=None,
    name_filter=None,
    predicate: Callable[[SelectionTarget], bool] | None = None,
    **defaults: Any,
):
    """
    Provide fill-missing defaults for NodeTemplates matched by the selector.

    Matching is performed on declarations (node name + node class), so `SelectionTarget.obj` is always None.
    """

    sel = build_selector(
        selector=selector, type_filter=type_filter, name_filter=name_filter, predicate=predicate
    )
    pf = parse_path_filter(path_filter) if path_filter is not None else None
    previous = _TEMPLATE_DEFAULTS_RULES_CVAR.get()
    token = _TEMPLATE_DEFAULTS_RULES_CVAR.set(previous + ((sel, pf, dict(defaults)),))
    try:
        yield
    finally:
        _TEMPLATE_DEFAULTS_RULES_CVAR.reset(token)


@contextmanager
def template_overrides_for(
    *,
    selector: Selector | None = None,
    path_filter: str | None = None,
    type_filter=None,
    name_filter=None,
    predicate: Callable[[SelectionTarget], bool] | None = None,
    **overrides: Any,
):
    """
    Provide force overrides for NodeTemplates matched by the selector.

    Matching is performed on declarations (node name + node class), so `SelectionTarget.obj` is always None.
    """

    sel = build_selector(
        selector=selector, type_filter=type_filter, name_filter=name_filter, predicate=predicate
    )
    pf = parse_path_filter(path_filter) if path_filter is not None else None
    previous = _TEMPLATE_OVERRIDES_RULES_CVAR.get()
    token = _TEMPLATE_OVERRIDES_RULES_CVAR.set(previous + ((sel, pf, dict(overrides)),))
    try:
        yield
    finally:
        _TEMPLATE_OVERRIDES_RULES_CVAR.reset(token)


@lru_cache(maxsize=None)
def _accepted_init_kwargs(node_cls: type) -> tuple[frozenset[str], bool]:
    """Return (accepted_kw_names, accepts_var_kwargs) for node_cls.__init__."""
    sig = inspect.signature(node_cls.__init__)
    params = list(sig.parameters.values())
    if params and params[0].name in {"self", "cls"}:
        params = params[1:]

    accepts_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
    accepted_kw_names = frozenset(
        p.name
        for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    )
    return accepted_kw_names, accepts_var_kwargs


def _safe_clone(value: Any, memo: dict[int, Any] | None = None) -> Any:
    """
    Clone a template config value.

    - Deep-copies built-in containers recursively (dict/list/tuple/set) so per-node configs don't share mutable
      containers.
    - For non-container objects, the default is *per-node instance* (prototype): attempt `copy.deepcopy`.
      If deepcopy fails, raise with a clear suggestion to use `Shared(...)` or `Factory(...)` explicitly.
    - Some objects are intended to be singletons/shared services. Such objects can opt-in
      by setting `__node_template_scope__ = "shared"` on the instance or its class, or by being wrapped in
      `Shared(...)`.

    This makes NodeTemplate behavior predictable:
    - Containers are always copied.
    - Custom objects are copied (factory-like) unless explicitly marked as shared.
    - Non-copyable objects must be explicitly scoped via Shared/Factory.
    """
    if memo is None:
        memo = {}

    obj_id = id(value)
    if obj_id in memo:
        return memo[obj_id]

    if isinstance(value, _IMMUTABLE_SCALARS):
        memo[obj_id] = value
        return value

    if isinstance(value, Shared):
        memo[obj_id] = value.value
        return value.value

    if isinstance(value, Factory):
        produced = value.make()
        memo[obj_id] = produced
        return produced

    scope = getattr(value, "__node_template_scope__", None)
    if scope is None:
        scope = getattr(getattr(value, "__class__", object), "__node_template_scope__", None)
    if isinstance(scope, str) and scope.lower() in {"shared", "singleton"}:
        memo[obj_id] = value
        return value

    if isinstance(value, dict):
        cloned: dict[Any, Any] = {}
        memo[obj_id] = cloned
        for k, v in value.items():
            cloned[_safe_clone(k, memo)] = _safe_clone(v, memo)
        return cloned

    if isinstance(value, list):
        cloned_list: list[Any] = []
        memo[obj_id] = cloned_list
        cloned_list.extend(_safe_clone(v, memo) for v in value)
        return cloned_list

    if isinstance(value, tuple):
        cloned_tuple = tuple(_safe_clone(v, memo) for v in value)
        memo[obj_id] = cloned_tuple
        return cloned_tuple

    if isinstance(value, set):
        cloned_set: set[Any] = set()
        memo[obj_id] = cloned_set
        for v in value:
            cloned_set.add(_safe_clone(v, memo))
        return cloned_set

    try:
        cloned_obj = copy.deepcopy(value, memo)
        memo[obj_id] = cloned_obj
        return cloned_obj
    except Exception:
        raise TypeError(
            "NodeTemplate cannot clone a non-container object of type "
            f"{type(value).__name__} (likely non-copyable runtime resource such as a lock/client/handle). "
            "Wrap it with Shared(obj) to share the instance, or Factory(lambda: ...) to create a fresh instance."
        )


class NodeTemplate(Generic[T]):
    """Declarative template for creating nodes inside graphs.

    A `NodeTemplate` is a lightweight configuration object that can be reused across graphs.
    It does not instantiate nodes directly; graphs materialize templates via `Graph.create_node()`
    so the created node is always owned by a graph.
    """

    def __init__(self, node_cls: Type[T], **default_kwargs):
        """Create a NodeTemplate.

        Args:
            node_cls: Node class to be materialized.
            **default_kwargs: Default constructor kwargs applied during materialization.
        """
        self.node_cls = node_cls
        self.prototype_config = default_kwargs

    def render_config(self, **override_kwargs) -> dict[str, Any]:
        final_config = _safe_clone(self.prototype_config)
        final_config.update(_safe_clone(override_kwargs))
        return final_config

    def __call__(self, *args: Any, **override_kwargs) -> "NodeTemplate[T]":
        """
        Create a derived template with overridden defaults.

        MASFactory graphs only accept Nodes created by Graph.create_node(), so NodeTemplate intentionally does NOT
        construct a Node instance directly.
        """
        if args:
            raise TypeError(
                "NodeTemplate(...) no longer materializes a Node. "
                "Use Graph.create_node(template, name=...) or declare nodes=[(name, template)]."
            )
        if "name" in override_kwargs:
            raise TypeError(
                "NodeTemplate(...) does not accept 'name'. "
                "Use Graph.create_node(template, name=...) or declare nodes=[(name, template)]."
            )
        if not override_kwargs:
            return self
        return self.clone(**override_kwargs)

    def _materialize(
        self,
        *,
        name: str,
        instantiate: Callable[..., Node],
        creation_path: tuple[str, ...] | None = None,
        **override_kwargs: Any,
    ) -> T:
        """
        Internal: materialize this template into a concrete Node instance.

        Graph/BaseGraph should call this during create_node(), so Nodes are always registered inside a Graph.
        """
        final_config = self.render_config(**override_kwargs)

        accepted_kw_names, accepts_var_kwargs = _accepted_init_kwargs(self.node_cls)

        def can_inject(key: str) -> bool:
            if key == "name":
                return False
            return accepts_var_kwargs or key in accepted_kw_names

        memo: dict[int, Any] = {}

        # Apply selector defaults (fill missing only, higher than global defaults).
        for sel, pf, cfg in reversed(_TEMPLATE_DEFAULTS_RULES_CVAR.get()):
            if not sel.match_declaration(name=name, cls=self.node_cls):
                continue
            if pf is not None:
                if creation_path is None or not match_path_filter(pf, creation_path):
                    continue
            for key, value in cfg.items():
                if key not in final_config and can_inject(key):
                    final_config[key] = _safe_clone(value, memo)

        # Apply global defaults (fill missing only).
        scoped_defaults = _TEMPLATE_DEFAULTS_CVAR.get()
        for key, value in scoped_defaults.items():
            if key not in final_config and can_inject(key):
                final_config[key] = _safe_clone(value, memo)

        # Apply global overrides (force overwrite).
        scoped_overrides = _TEMPLATE_OVERRIDES_CVAR.get()
        for key, value in scoped_overrides.items():
            if can_inject(key):
                final_config[key] = _safe_clone(value, memo)

        # Apply selector overrides (force overwrite, higher than global overrides).
        for sel, pf, cfg in _TEMPLATE_OVERRIDES_RULES_CVAR.get():
            if not sel.match_declaration(name=name, cls=self.node_cls):
                continue
            if pf is not None:
                if creation_path is None or not match_path_filter(pf, creation_path):
                    continue
            for key, value in cfg.items():
                if can_inject(key):
                    final_config[key] = _safe_clone(value, memo)
        return instantiate(self.node_cls, name=name, **final_config)  # type: ignore

    def clone(self, **override_kwargs) -> 'NodeTemplate[T]':
        new_prototype_config = _safe_clone(self.prototype_config)
        new_prototype_config.update(_safe_clone(override_kwargs))

        return NodeTemplate(
            node_cls=self.node_cls,
            **new_prototype_config
        )


__all__ = [
    "NodeTemplate",
    "Shared",
    "Factory",
    "template_defaults",
    "template_overrides",
    "template_defaults_for",
    "template_overrides_for",
]
    
