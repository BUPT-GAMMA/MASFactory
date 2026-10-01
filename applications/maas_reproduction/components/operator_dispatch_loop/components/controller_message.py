"""Small, explicit control contract for the MASFactory Loop controller."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LoopControllerMessage:
    """Only cursor/iteration/continue state may cross controller edges."""

    cursor: int
    iteration: int
    should_continue: bool

    def __post_init__(self) -> None:
        if isinstance(self.cursor, bool) or not isinstance(self.cursor, int) or self.cursor < 0:
            raise ValueError("cursor must be a non-negative integer")
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration < 0:
            raise ValueError("iteration must be a non-negative integer")
        if not isinstance(self.should_continue, bool):
            raise TypeError("should_continue must be a bool")


__all__ = ["LoopControllerMessage"]
