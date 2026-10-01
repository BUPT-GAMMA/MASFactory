"""Pure operator-name routing for the native dispatch loop."""

from __future__ import annotations

from typing import Callable

from masfactory import LogicSwitch as _LogicSwitch


def operator_route(operator_name: str) -> Callable[[dict, dict], bool]:
    """Return a side-effect-free predicate for one operator name."""
    return lambda message, attributes: (
        message["operator_invocation"].operator_name == operator_name
        if hasattr(message["operator_invocation"], "operator_name")
        else message["operator_invocation"]["operator_name"] == operator_name
    )


class DispatchLogicSwitch(_LogicSwitch):
    """LogicSwitch specialization kept as a named Task 5 seam."""


__all__ = ["DispatchLogicSwitch", "operator_route"]
