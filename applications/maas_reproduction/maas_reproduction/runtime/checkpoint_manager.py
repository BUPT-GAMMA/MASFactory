"""Atomic training checkpoints for the MaAS reproduction runtime.

Checkpoints are a runtime adapter: model/optimizer state is persisted together
with the training position and all random-number-generator state needed to
resume a batch boundary.  Policy tensors (which may still be attached to an
autograd graph) are deliberately rejected before serialization.
"""

from __future__ import annotations

import copy
import os
import random
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


class CheckpointError(RuntimeError):
    """Raised when a checkpoint is malformed or contains live tensors."""


def _contains_live_tensor(value: Any) -> bool:
    """Return whether ``value`` contains a tensor attached to autograd."""
    try:
        import torch
    except ImportError:  # pragma: no cover - torch is a project dependency
        return False
    if isinstance(value, torch.Tensor):
        return bool(value.requires_grad)
    if isinstance(value, Mapping):
        return any(_contains_live_tensor(k) or _contains_live_tensor(v) for k, v in value.items())
    if isinstance(value, (tuple, list, set)):
        return any(_contains_live_tensor(item) for item in value)
    return False


def _detached_copy(value: Any) -> Any:
    """Copy checkpoint data while detaching ordinary state tensors."""
    try:
        import torch
    except ImportError:  # pragma: no cover
        return copy.deepcopy(value)
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().clone()
    if isinstance(value, Mapping):
        return {k: _detached_copy(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(_detached_copy(v) for v in value)
    if isinstance(value, list):
        return [_detached_copy(v) for v in value]
    return copy.deepcopy(value)


def _rng_state() -> dict[str, Any]:
    state: dict[str, Any] = {"python": random.getstate()}
    try:
        import numpy as np
        state["numpy"] = np.random.get_state()
    except ImportError:
        pass
    try:
        import torch
        state["torch"] = torch.random.get_rng_state().cpu()
        if torch.cuda.is_available():
            state["torch_cuda"] = [s.cpu() for s in torch.cuda.get_rng_state_all()]
    except ImportError:
        pass
    return state


def _restore_rng(state: Mapping[str, Any]) -> None:
    random.setstate(state["python"])
    if "numpy" in state:
        import numpy as np
        np.random.set_state(state["numpy"])
    if "torch" in state:
        import torch
        torch.random.set_rng_state(state["torch"])
        if "torch_cuda" in state and torch.cuda.is_available():
            torch.cuda.set_rng_state_all(state["torch_cuda"])


class CheckpointManager:
    """Save and restore complete training state at batch boundaries."""

    FORMAT_VERSION = 1

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        controller: Any,
        optimizer: Any,
        *,
        cursor: int,
        epoch: int,
        operator_catalog: Sequence[str],
        path: str | os.PathLike[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
        pending_gradients: int = 0,
    ) -> Path:
        """Persist a checkpoint, atomically replacing the target file.

        ``pending_gradients`` is the number of policy-gradient tensors that are
        still waiting for an optimizer step.  Only ``0`` is serializable: the
        accumulator is never persisted, so a checkpoint taken in the middle of a
        batch would silently drop those gradients on resume.
        """
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ValueError("cursor must be a non-negative int")
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            raise ValueError("epoch must be a non-negative int")
        catalog = tuple(operator_catalog)
        if any(not isinstance(name, str) or not name for name in catalog):
            raise ValueError("operator_catalog must contain non-empty names")
        if not hasattr(controller, "state_dict") or not hasattr(optimizer, "state_dict"):
            raise TypeError("controller and optimizer must expose state_dict()")
        if isinstance(pending_gradients, bool) or not isinstance(pending_gradients, int) or pending_gradients < 0:
            raise ValueError("pending_gradients must be a non-negative int")
        if pending_gradients:
            raise CheckpointError("checkpoint must be saved at a batch boundary")
        payload = {
            "format_version": self.FORMAT_VERSION,
            "controller": _detached_copy(controller.state_dict()),
            "optimizer": _detached_copy(optimizer.state_dict()),
            "cursor": cursor,
            "epoch": epoch,
            "operator_catalog": catalog,
            "rng": _rng_state(),
            "metadata": dict(metadata or {}),
            "pending_gradient_count": pending_gradients,
        }
        if _contains_live_tensor(payload):
            raise CheckpointError("checkpoint contains a live autograd Tensor")
        target = Path(path) if path is not None else self.directory / "latest.pt"
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        os.close(fd)
        try:
            import torch
            torch.save(payload, temporary)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    save_batch = save
    save_checkpoint = save

    def load(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        controller: Any | None = None,
        optimizer: Any | None = None,
        expected_operator_catalog: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Load state, optionally restoring controller/optimizer and RNG."""
        import torch
        target = Path(path) if path is not None else self.directory / "latest.pt"
        try:
            try:
                payload = torch.load(target, map_location="cpu", weights_only=False)
            except TypeError:  # older torch releases have no weights_only flag
                payload = torch.load(target, map_location="cpu")
        except Exception as exc:
            raise CheckpointError(f"unable to load checkpoint: {target}") from exc
        if not isinstance(payload, Mapping) or payload.get("format_version") != self.FORMAT_VERSION:
            raise CheckpointError("unsupported or malformed checkpoint")
        pending = payload.get("pending_gradient_count", 0)
        if isinstance(pending, bool) or not isinstance(pending, int) or pending < 0:
            raise CheckpointError("malformed pending_gradient_count in checkpoint")
        if pending:
            raise CheckpointError("checkpoint was not saved at a batch boundary")
        catalog = tuple(payload.get("operator_catalog", ()))
        if expected_operator_catalog is not None and catalog != tuple(expected_operator_catalog):
            raise CheckpointError("operator catalog does not match checkpoint")
        if _contains_live_tensor(payload):
            raise CheckpointError("checkpoint contains a live autograd Tensor")
        if controller is not None:
            controller.load_state_dict(payload["controller"])
        if optimizer is not None:
            optimizer.load_state_dict(payload["optimizer"])
        _restore_rng(payload["rng"])
        return dict(payload)

    load_batch = load
    load_checkpoint = load


__all__ = ["CheckpointError", "CheckpointManager"]
