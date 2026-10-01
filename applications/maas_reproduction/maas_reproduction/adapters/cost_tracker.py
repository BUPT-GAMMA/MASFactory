"""Per-sample cost accounting for shared model cost managers.

The original MaAS code exposes a cumulative ``total_cost`` counter.  This
adapter deliberately keeps the counter interaction in one place and turns a
pair of snapshots into an explicit :class:`CostResult`; callers must never
silently interpret a missing or decreasing counter as zero cost.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from applications.maas_reproduction.maas_reproduction.schemas import CostResult


@dataclass(frozen=True, slots=True)
class CostSnapshot:
    """Immutable cumulative usage observed at one point in a sample."""

    total_cost: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reliable: bool = True
    reliability_error: str | None = None


class CostTracker:
    """Read cumulative cost from an injected manager and calculate deltas."""

    def __init__(self, manager: Any) -> None:
        if manager is None:
            raise ValueError("manager is required")
        self.manager = manager

    def snapshot(self) -> CostSnapshot:
        """Capture cost and (when available) token counters.

        Access errors and malformed values are intentionally raised here so a
        finalizer can report an unreliable cost rather than fabricate one.
        """
        getter = getattr(self.manager, "get_total_cost", None)
        value = getter() if callable(getter) else getattr(self.manager, "total_cost")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("total cost must be finite")
        def counter(name: str) -> int | None:
            getter = getattr(self.manager, f"get_total_{name}", None)
            raw = getter() if callable(getter) else getattr(self.manager, f"total_{name}", None)
            return int(raw) if raw is not None else None
        reliable = bool(getattr(self.manager, "cost_reliable", True))
        reliability_error = getattr(self.manager, "cost_reliability_error", None)
        return CostSnapshot(
            value,
            counter("prompt_tokens"),
            counter("completion_tokens"),
            reliable,
            str(reliability_error) if reliability_error else None,
        )

    @staticmethod
    def delta(before: CostSnapshot, after: CostSnapshot) -> CostResult:
        """Return a trusted non-negative delta, or a diagnostic failure."""
        if not isinstance(before, CostSnapshot) or not isinstance(after, CostSnapshot):
            return CostResult(None, False, "invalid cost snapshot")
        if not before.reliable or not after.reliable:
            return CostResult(
                None,
                False,
                after.reliability_error
                or before.reliability_error
                or "cost is not reliable",
            )
        value = after.total_cost - before.total_cost
        if not math.isfinite(value):
            return CostResult(None, False, "cost delta is not finite")
        token_reset = any(
            previous is not None and current is not None and current < previous
            for previous, current in (
                (before.prompt_tokens, after.prompt_tokens),
                (before.completion_tokens, after.completion_tokens),
            )
        )
        if value < 0 or token_reset:
            return CostResult(value, False, "cost tracker reset or decreased")
        return CostResult(value, True)


__all__ = ["CostSnapshot", "CostTracker"]
