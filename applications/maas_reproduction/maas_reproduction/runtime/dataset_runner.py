"""Sequential dataset execution lifecycle for Task 2."""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
import math
import time
from typing import Any

from ..schemas import FailureSource, SampleResult
from ..source_compat import RecoverableModelOutputError


class DatasetRunner:
    """Invoke a RootGraph once per sample with isolated invocation state."""

    def __init__(self, *, graph: object, dataset: Iterable[Mapping[str, Any]], start_index: int = 0,
                 epochs: int = 1, batch_accumulator: object | None = None,
                 checkpoint_manager: object | None = None, controller: object | None = None,
                 optimizer: object | None = None, operator_catalog: Iterable[str] = (),
                 artifact_store: object | None = None,
                 run_config: Mapping[str, Any] | None = None,
                 run_logger: object | None = None) -> None:
        if not hasattr(graph, "invoke"):
            raise TypeError("graph must expose invoke")
        if start_index < 0:
            raise ValueError("start_index must be non-negative")
        self.graph = graph
        self.dataset = list(dataset)
        if isinstance(epochs, bool) or not isinstance(epochs, int) or epochs < 1:
            raise ValueError("epochs must be a positive integer")
        self.epochs = epochs
        self.batch_accumulator = batch_accumulator
        self.checkpoint_manager = checkpoint_manager
        self.controller, self.optimizer = controller, optimizer
        self.operator_catalog = tuple(operator_catalog)
        self.artifact_store = artifact_store
        self.run_config = dict(run_config or {})
        self.run_logger = run_logger
        self.cursor = start_index
        self.epoch = 0
        self._metrics_state: dict[str, Any] = {
            "sample_count": 0, "success_count": 0, "failure_count": 0,
            "score_sum": 0.0, "cost_sum": 0.0, "cost_count": 0,
            "update_count": 0, "completed_epochs": 0,
        }

    def _pending_gradients(self) -> int:
        """Number of policy tensors still waiting for an optimizer step."""
        return int(getattr(self.batch_accumulator, "pending_count", 0) or 0)

    def _at_batch_boundary(self) -> bool:
        """Whether no policy gradient is pending, so a checkpoint is resumable.

        The accumulator is never serialized, so a mid-batch checkpoint would
        drop the gradients it holds.  A runner without an accumulator has no
        gradient state to lose and is therefore always at a boundary.
        """
        if self.batch_accumulator is None:
            return True
        return self._pending_gradients() == 0

    def run(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Run all configured epochs and return detached public results.

        ``iter_run`` contains the lifecycle implementation; this method keeps
        the existing list-returning API for callers that need collected output.
        """
        return list(self.iter_run(limit=limit))

    def _save_checkpoint(self, *, epoch: int, cursor: int, history: bool = False) -> None:
        if self.checkpoint_manager is None or self.controller is None or self.optimizer is None:
            return
        # Enforced, not documented: the pending policy gradients live only in the
        # accumulator, which is never serialized, so saving between boundaries
        # would lose them on resume while the cursor claimed they were applied.
        pending = self._pending_gradients()
        if pending:
            raise RuntimeError("checkpoint must be saved at a batch boundary")
        metadata = {"runner_metrics": dict(self._metrics_state)}
        self.checkpoint_manager.save(
            self.controller,
            self.optimizer,
            cursor=cursor,
            epoch=epoch,
            operator_catalog=self.operator_catalog,
            metadata=metadata,
            pending_gradients=pending,
        )
        if history:
            directory = getattr(self.checkpoint_manager, "directory", None)
            if directory is not None:
                self.checkpoint_manager.save(
                    self.controller,
                    self.optimizer,
                    cursor=cursor,
                    epoch=epoch,
                    operator_catalog=self.operator_catalog,
                    path=directory / f"checkpoint_epoch_{epoch:03d}.pt",
                    metadata=metadata,
                    pending_gradients=pending,
                )

    def restore_checkpoint(self, payload: Mapping[str, Any]) -> None:
        """Apply the runner position and public counters from a checkpoint."""
        cursor, epoch = payload.get("cursor"), payload.get("epoch")
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ValueError("checkpoint cursor must be a non-negative int")
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
            raise ValueError("checkpoint epoch must be a non-negative int")
        if epoch > self.epochs:
            raise ValueError("checkpoint epoch exceeds configured epochs")
        if cursor > len(self.dataset):
            raise ValueError("checkpoint cursor exceeds dataset length")
        metadata = payload.get("metadata", {})
        saved_metrics = metadata.get("runner_metrics") if isinstance(metadata, Mapping) else None
        if isinstance(saved_metrics, Mapping) and saved_metrics:
            restored = self._validate_metrics(saved_metrics, cursor=cursor, epoch=epoch)
            # Update in place: ``iter_run`` aliases this dict, so rebinding it
            # would leave a running iterator counting into a discarded copy.
            self._metrics_state.update(restored)
        self.cursor, self.epoch = cursor, epoch
        if "pending_gradient_count" not in payload:
            # Pre-boundary checkpoints cannot prove they were taken between
            # batches; their cursor may sit inside one whose gradients are gone.
            self._log_event("checkpoint_boundary_marker_missing")

    _COUNTER_KEYS = ("sample_count", "success_count", "failure_count",
                     "cost_count", "update_count", "completed_epochs")
    _SUM_KEYS = ("score_sum", "cost_sum")

    def _validate_metrics(self, saved: Mapping[str, Any], *, cursor: int, epoch: int) -> dict[str, Any]:
        """Validate restored counters against the position they were frozen at."""
        restored: dict[str, Any] = {}
        for key in self._COUNTER_KEYS:
            if key not in saved:
                continue
            value = saved[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"checkpoint metric {key} must be a non-negative int")
            restored[key] = value
        for key in self._SUM_KEYS:
            if key not in saved:
                continue
            value = saved[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"checkpoint metric {key} must be a finite number")
            restored[key] = float(value)
        # A checkpoint is one atomic resume point: the counters must agree with
        # the cursor/epoch they were frozen with, otherwise the run resumes from
        # a position its own bookkeeping does not describe.
        if "completed_epochs" in restored and restored["completed_epochs"] != epoch:
            raise ValueError(
                f"checkpoint metric completed_epochs={restored['completed_epochs']} disagrees with epoch={epoch}"
            )
        if "sample_count" in restored and "completed_epochs" in restored:
            expected = restored["completed_epochs"] * len(self.dataset) + cursor
            if restored["sample_count"] != expected:
                raise ValueError(
                    f"checkpoint metrics disagree with its position: sample_count={restored['sample_count']} "
                    f"but cursor/epoch imply {expected}"
                )
        return restored

    def _log_error(self, *, stage: str, error: BaseException | str, **fields: Any) -> None:
        logger = self.run_logger
        if logger is not None and callable(getattr(logger, "error", None)):
            logger.error(stage=stage, error=error, **fields)

    def _log_event(self, event: str, **fields: Any) -> None:
        logger = self.run_logger
        if logger is not None and callable(getattr(logger, "event", None)):
            logger.event(event, **fields)

    def iter_run(self, *, limit: int | None = None) -> Iterator[dict[str, Any]]:
        """Stream one detached public result at a time across all epochs."""
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if self.artifact_store is not None and self.run_config:
            try:
                self.artifact_store.write_config(self.run_config)
            except Exception as exc:
                self._log_error(stage="write_config", error=exc)
                raise
        if limit == 0:
            self._log_event("run_stopped", epoch=self.epoch, cursor=self.cursor, reason="limit_zero")
            return

        metrics = self._metrics_state
        self._log_event("run_started", epoch=self.epoch, cursor=self.cursor)

        for epoch in range(self.epoch, self.epochs):
            start_cursor = self.cursor if epoch == self.epoch else 0
            processed = 0
            truncated = False
            for offset, sample in enumerate(self.dataset):
                if offset < start_cursor:
                    continue
                if limit is not None and processed >= limit:
                    truncated = True
                    break
                if not isinstance(sample, Mapping):
                    error = TypeError("dataset samples must be mappings")
                    self._log_error(stage="validate_sample", error=error, epoch=epoch, problem_index=offset)
                    raise error
                payload = dict(sample)
                payload.setdefault("problem_index", offset)
                started = time.perf_counter()
                try:
                    output = self.graph.invoke({"sample": payload})
                except RecoverableModelOutputError as exc:
                    self._log_error(
                        stage="recoverable_model_output", error=exc, epoch=epoch,
                        problem_index=payload.get("problem_index", offset),
                    )
                    output = {"sample_result": SampleResult(
                        problem_index=int(payload.get("problem_index", offset)),
                        prediction=None,
                        score=None,
                        cost_delta=None,
                        status="failed",
                        failure_source=FailureSource.ROUTE_EXECUTION,
                        result_valid=False,
                        cost_reliable=False,
                        evaluation_reliable=False,
                        policy_log_prob_value=None,
                        utility=None,
                        update_performed=False,
                        skip_reason="invalid_architecture_result",
                        loss_value=None,
                        failure_detail=f"{type(exc).__name__}: {exc}",
                    )}
                except Exception as exc:
                    self._log_error(
                        stage="graph_invoke", error=exc, epoch=epoch,
                        problem_index=payload.get("problem_index", offset),
                    )
                    raise
                if isinstance(output, tuple):
                    output = output[0]
                if not isinstance(output, Mapping) or "sample_result" not in output:
                    error = ValueError("RootGraph output must contain sample_result")
                    self._log_error(stage="validate_graph_output", error=error, epoch=epoch, problem_index=offset)
                    raise error
                record = output["sample_result"]
                if hasattr(record, "to_dict"):
                    record = record.to_dict()
                if not isinstance(record, Mapping):
                    error = TypeError("sample_result must be a mapping")
                    self._log_error(stage="validate_sample_result", error=error, epoch=epoch, problem_index=offset)
                    raise error
                public_record = dict(record)
                if self.artifact_store is not None:
                    try:
                        self.artifact_store.write_sample_result(public_record)
                    except Exception as exc:
                        self._log_error(
                            stage="write_sample_result", error=exc, epoch=epoch,
                            problem_index=public_record.get("problem_index", offset),
                        )
                        raise

                metrics["sample_count"] += 1
                if public_record.get("status") in {"success", "completed"}:
                    metrics["success_count"] += 1
                else:
                    metrics["failure_count"] += 1
                if isinstance(public_record.get("score"), (int, float)):
                    metrics["score_sum"] += float(public_record["score"])
                if isinstance(public_record.get("cost_delta"), (int, float)):
                    metrics["cost_sum"] += float(public_record["cost_delta"])
                    metrics["cost_count"] += 1
                if public_record.get("update_performed"):
                    metrics["update_count"] += 1

                self.cursor = offset + 1
                processed += 1
                # Batch boundary only: the graph has already stepped the
                # optimizer if this sample completed a batch, so an empty
                # accumulator is exactly the resumable position.
                if self._at_batch_boundary():
                    try:
                        self._save_checkpoint(epoch=epoch, cursor=self.cursor)
                    except Exception as exc:
                        self._log_error(
                            stage="save_checkpoint", error=exc, epoch=epoch,
                            problem_index=public_record.get("problem_index", offset),
                        )
                        raise
                self._log_event(
                    "sample_completed",
                    epoch=epoch,
                    problem_index=public_record.get("problem_index", offset),
                    operator_name=public_record.get("operator_name", "unknown"),
                    status=public_record.get("status", "unknown"),
                    failure_source=public_record.get("failure_source"),
                    cost_reliable=bool(public_record.get("cost_reliable", False)),
                    evaluation_reliable=bool(public_record.get("evaluation_reliable", False)),
                    duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
                )
                yield public_record

            # Apply a trailing partial batch before the boundary marker is
            # written: those gradients were paid for, and the accumulator is not
            # persisted, so they would otherwise be dropped on exit.
            if self._pending_gradients():
                try:
                    flush_result = self.batch_accumulator.flush_partial()
                except Exception as exc:
                    self._log_error(stage="flush_partial_batch", error=exc, epoch=epoch)
                    raise
                if isinstance(flush_result, Mapping) and flush_result.get("update_performed"):
                    metrics["update_count"] += 1

            if truncated:
                # ``limit`` stops the run at a batch boundary *inside* the epoch,
                # so the epoch is not complete: neither ``completed_epochs`` nor
                # ``self.epoch`` may advance and the cursor stays put, letting
                # the next invocation resume the same epoch from this boundary.
                # The flush above may leave a shortened batch behind, which is
                # the price of not discarding gradients already paid for.
                self._log_event("run_truncated", epoch=epoch, cursor=self.cursor, processed=processed)
                try:
                    self._save_checkpoint(epoch=epoch, cursor=self.cursor)
                except Exception as exc:
                    self._log_error(stage="save_checkpoint", error=exc, epoch=epoch)
                    raise
                break
            metrics["completed_epochs"] += 1
            self.epoch = epoch + 1
            self.cursor = 0
            try:
                self._save_checkpoint(epoch=self.epoch, cursor=0, history=True)
            except Exception as exc:
                self._log_error(stage="save_epoch_checkpoint", error=exc, epoch=self.epoch)
                raise

        if self.artifact_store is not None:
            sample_count = metrics["sample_count"]
            metrics_out = {
                "sample_count": sample_count,
                "success_count": metrics["success_count"],
                "failure_count": metrics["failure_count"],
                "average_score": metrics["score_sum"] / sample_count if sample_count else None,
                "average_cost": metrics["cost_sum"] / metrics["cost_count"] if metrics["cost_count"] else None,
                "update_count": metrics["update_count"],
                "completed_epochs": metrics["completed_epochs"],
            }
            try:
                self.artifact_store.write_metrics(metrics_out)
            except Exception as exc:
                self._log_error(stage="write_metrics", error=exc)
                raise
        self._log_event(
            "run_completed",
            epoch=self.epoch,
            cursor=self.cursor,
            sample_count=metrics["sample_count"],
            completed_epochs=metrics["completed_epochs"],
        )


__all__ = ["DatasetRunner"]
