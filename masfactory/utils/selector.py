from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SelectionTarget:
    """
    A small, uniform view of "something selectable".

    This lets us share the same selector semantics across:
    - runtime hook registration (we have an object instance)
    - NodeTemplate materialization (we only have name + class)
    """

    name: str | None
    cls: type | None
    obj: object | None = None

    @classmethod
    def from_obj(cls, obj: object) -> "SelectionTarget":
        return cls(name=getattr(obj, "name", None), cls=type(obj), obj=obj)


class Selector:
    """
    Filters by (type, name, predicate).

    - type_filter: a type or an iterable of types
    - name_filter:
        - str: exact match
        - list/set/tuple: membership
        - regex-like: has callable `.match(name)`
        - callable: name -> bool
    - predicate: SelectionTarget -> bool

    Two explicit entry points exist to keep APIs clear:
    - match(obj): runtime instance matching (hooks)
    - match_declaration(name, cls): declaration matching (NodeTemplate)
    """

    def __init__(
        self,
        *,
        type_filter=None,
        name_filter=None,
        predicate: Callable[[SelectionTarget], bool] | None = None,
    ):
        """Create a selector.

        Args:
            type_filter: Type or tuple/list/set of types to match by `issubclass`.
            name_filter: Name filter. Supported forms include exact string, set/list/tuple
                membership, regex-like objects with `.match(name)`, or a callable `name -> bool`.
            predicate: Optional predicate applied to the normalized `SelectionTarget`.
        """
        self._type_filter = self._normalize_type_filter(type_filter)
        self._name_filter = name_filter
        self._predicate = predicate

    def match(self, obj: object) -> bool:
        """Match a runtime instance against this selector."""
        return self._match_target(SelectionTarget.from_obj(obj))

    def match_declaration(self, *, name: str | None, cls: type | None) -> bool:
        """Match a (name, type) declaration against this selector.

        This is used by NodeTemplate materialization where only a declared name/type is
        available (no live instance).
        """
        return self._match_target(SelectionTarget(name=name, cls=cls, obj=None))

    def _match_target(self, target: SelectionTarget) -> bool:
        if self._type_filter:
            if target.cls is None:
                return False
            if not issubclass(target.cls, self._type_filter):
                return False

        if self._name_filter is not None:
            if target.name is None:
                return False
            name = target.name

            if isinstance(self._name_filter, str):
                if name != self._name_filter:
                    return False
            elif isinstance(self._name_filter, (list, set, tuple)):
                if name not in self._name_filter:
                    return False
            elif hasattr(self._name_filter, "match") and callable(getattr(self._name_filter, "match")):
                if not self._name_filter.match(name):
                    return False
            elif callable(self._name_filter):
                if not self._name_filter(name):
                    return False
            else:
                if name != self._name_filter:
                    return False

        if self._predicate and not self._predicate(target):
            return False

        return True

    @staticmethod
    def _normalize_type_filter(type_filter):
        if type_filter is None:
            return None
        if isinstance(type_filter, (list, set, tuple)):
            return tuple(type_filter)
        if isinstance(type_filter, type):
            return (type_filter,)
        raise TypeError("type_filter must be a type or an iterable of types")


def build_selector(
    selector: "Selector | None" = None,
    *,
    type_filter=None,
    name_filter=None,
    predicate: Callable[[SelectionTarget], bool] | None = None,
) -> Selector:
    """
    Helper: prefer an existing selector, otherwise build one from filters.
    """

    if selector is not None:
        return selector
    return Selector(type_filter=type_filter, name_filter=name_filter, predicate=predicate)


__all__ = ["SelectionTarget", "Selector", "build_selector"]
