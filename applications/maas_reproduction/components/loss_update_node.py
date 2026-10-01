from __future__ import annotations
from typing import Any
from masfactory.components.custom_node import CustomNode
from applications.maas_reproduction.maas_reproduction.training.training_signal import build_training_signal


class LossUpdateNode(CustomNode):
    """Convert an evaluation into a signal and optionally enqueue it."""
    def __init__(self, name: str = "loss_update", batch_accumulator: object | None = None, **kwargs: Any) -> None:
        self.batch_accumulator = batch_accumulator
        super().__init__(name=name, forward=self._update, **kwargs)

    def _update(self, message: dict[str, object]) -> dict[str, object]:
        evaluation = message.get("evaluation_result")
        signal = build_training_signal(evaluation)  # type: ignore[arg-type]
        if signal.should_update and self.batch_accumulator is not None:
            add = getattr(self.batch_accumulator, "add")
            policy_log_prob = (evaluation.get("policy_log_prob") if isinstance(evaluation, dict) else getattr(evaluation, "policy_log_prob", None))
            result = add(
                policy_log_prob=policy_log_prob,
                utility=signal.utility,
            )
            if isinstance(result, dict):
                # BatchAccumulator returns detached optimizer metadata.  The
                # signal's utility is still public sample metadata and must
                # survive a successful optimizer step.
                update_result = dict(result)
                update_result["utility"] = signal.utility
                return {"update_result": update_result}
        return {"update_result": {"update_performed": signal.should_update, "skip_reason": signal.skip_reason, "utility": signal.utility}}


__all__ = ["LossUpdateNode"]
