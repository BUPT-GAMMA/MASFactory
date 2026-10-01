"""Accumulate eligible policy samples and apply the frozen MaAS loss."""

from __future__ import annotations

import math
from typing import Any


class BatchAccumulator:
    """Own the short-lived policy-gradient tensors for one training batch.

    ``policy_log_prob`` values are deliberately retained by identity until the
    optimizer step.  Public callers receive only detached scalar metadata from
    the returned dictionary; no autograd tensor escapes this boundary.
    """

    def __init__(self, optimizer: Any, batch_size: int) -> None:
        if optimizer is None:
            raise TypeError("optimizer is required")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int):
            raise TypeError("batch_size must be an int")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.optimizer = optimizer
        self.batch_size = batch_size
        self._policy_log_probs: list[Any] = []
        self._utilities: list[float] = []
        self.last_loss_value: float | None = None

    @property
    def pending_count(self) -> int:
        return len(self._policy_log_probs)

    @property
    def has_live_tensors(self) -> bool:
        return bool(self._policy_log_probs)

    def add(self, *, policy_log_prob: Any, utility: float | int) -> dict[str, object]:
        """Queue one eligible sample and step when the batch becomes full."""
        if policy_log_prob is None:
            raise ValueError("policy_log_prob is required")
        if isinstance(utility, bool) or not isinstance(utility, (int, float)):
            raise TypeError("utility must be a real number")
        utility_value = float(utility)
        if not math.isfinite(utility_value):
            raise ValueError("utility must be finite")
        self._policy_log_probs.append(policy_log_prob)
        self._utilities.append(utility_value)
        if self.pending_count >= self.batch_size:
            return self.flush()
        return {
            "update_performed": False,
            "pending_count": self.pending_count,
            "loss_value": None,
        }

    def flush_partial(self) -> dict[str, object]:
        """Apply a final non-full batch, if one is pending."""
        return self.flush()

    def flush(self) -> dict[str, object]:
        """Compute the mean policy loss, update the optimizer, and clear state."""
        if not self._policy_log_probs:
            return {
                "update_performed": False,
                "pending_count": 0,
                "loss_value": None,
            }

        log_probs = self._policy_log_probs
        utilities = self._utilities
        self._policy_log_probs = []
        self._utilities = []
        try:
            import torch

            stacked = torch.stack(tuple(log_probs))
            utility_tensor = torch.as_tensor(
                utilities, dtype=stacked.dtype, device=stacked.device
            )
            loss = -(stacked * utility_tensor).mean()
            loss_value = float(loss.detach().cpu().item())
            self.last_loss_value = loss_value
            if loss.requires_grad:
                loss.backward()
                self.optimizer.step()
                self.optimizer.zero_grad()
                return {
                    "update_performed": True,
                    "pending_count": 0,
                    "batch_size": len(log_probs),
                    "loss_value": loss_value,
                }
            self.optimizer.zero_grad()
            return {
                "update_performed": False,
                "pending_count": 0,
                "batch_size": len(log_probs),
                "loss_value": loss_value,
                "skip_reason": "loss_does_not_require_grad",
            }
        finally:
            # Do not retain graph-bearing values after a step or failed attempt.
            log_probs.clear()
            utilities.clear()


__all__ = ["BatchAccumulator"]
