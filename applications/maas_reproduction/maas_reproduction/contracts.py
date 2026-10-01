"""Frozen behavioral contracts for the MaAS reproduction.

This module is the machine-readable outcome of Task 0.  It records the
reproduction target; it does not add behavior that exists only in the paper.

The operator catalogs, controller sampling constants, EarlyStop normalization,
log-probability reduction, utility, and batch loss match the behavior recorded
in ``maas_source.md``.  The cost contract intentionally follows the higher-
priority reproduction specification: cost is measured per sample and must be
reliably attributable.  The source's cross-sample ``previous_cost`` subtraction
is not reproduced because it can produce negative or unrelated deltas.

Contract summary
----------------
* Routes are flattened in layer-major, then position-major order.
* The first layer's sampled EarlyStop is replaced by Generate and applies the
  source's -1.5 log-probability adjustment; it is not dispatched as a marker.
  A later EarlyStop remains a deterministic control marker and prevents
  sampling/executing later layers.
* Route policy log-probability is the sum of selected log-probabilities within
  each sampled layer, then the sum across sampled layers.  It remains attached
  to autograd until backward completes.
* A legal OperatorResult is a structured result with a non-empty operator name
  and status.  Recoverable statuses such as ``timeout`` remain legal.
* A legal ArchitectureResult has a non-empty, scoreable prediction.  Result
  validity is independent of failure attribution.
* Cost is reliable only when both snapshots and delta calculation succeed, the
  finite delta is non-negative, the tracker was not reset, and retries count.
* Evaluation is reliable only for a valid architecture result when the dataset
  scorer completes and returns a finite score.
* Utility is exactly ``score - 3.0 * cost_delta``.  FailureSource never changes
  it and no penalty, bonus, clipping, or artificial advantage is added.
* Policy loss is ``-(policy_log_prob * utility).mean()`` over eligible samples
  in the batch.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping


GENERATE_OPERATOR: Final = "Generate"
EARLY_STOP_OPERATOR: Final = "EarlyStop"

OPERATOR_CATALOGS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "GSM8K": (
            "Generate",
            "GenerateCoT",
            "MultiGenerateCoT",
            "ScEnsemble",
            "Programmer",
            "SelfRefine",
            "EarlyStop",
        ),
        "MATH": (
            "Generate",
            "GenerateCoT",
            "MultiGenerateCoT",
            "ScEnsemble",
            "Programmer",
            "SelfRefine",
            "EarlyStop",
        ),
        "HumanEval": (
            "Generate",
            "GenerateCoT",
            "MultiGenerateCoT",
            "ScEnsemble",
            "Test",
            "SelfRefine",
            "EarlyStop",
        ),
    }
)

BOOTSTRAP_OPERATOR_ORDER: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "GSM8K": (),
        "MATH": ("Programmer", "Generate"),
        "HumanEval": (),
    }
)

ROUTE_EXPANSION_ORDER: Final = "layer_major_then_position"
POLICY_LAYER_COUNT: Final = 4
OPERATOR_SELECTION_THRESHOLD: Final = 0.3
OPERATOR_SAMPLING_WITH_REPLACEMENT: Final = False
POLICY_LOG_PROB_REDUCTION: Final = "sum_selected_then_sum_layers"
FIRST_LAYER_EARLY_STOP_REPLACEMENT: Final = GENERATE_OPERATOR
FIRST_LAYER_EARLY_STOP_LOG_PROB_ADJUSTMENT: Final = -1.5
UTILITY_COST_COEFFICIENT: Final = 3.0
POLICY_LOSS_SIGN: Final = -1.0
POLICY_LOSS_REDUCTION: Final = "mean_over_eligible_batch"

COST_RELIABILITY_REQUIREMENTS: Final = (
    "before_snapshot_succeeded",
    "after_snapshot_succeeded",
    "delta_succeeded",
    "delta_is_finite",
    "delta_is_non_negative",
    "tracker_not_reset",
    "retries_accounted_for",
)

EVALUATION_RELIABILITY_REQUIREMENTS: Final = (
    "architecture_result_valid",
    "scorer_succeeded",
    "score_is_finite",
)

TRAINING_SKIP_REASONS: Final = frozenset(
    {
        "invalid_architecture_result",
        "unreliable_cost",
        "unreliable_evaluation",
        "missing_policy_log_prob",
    }
)


def operator_catalog_for(dataset: str) -> tuple[str, ...]:
    """Return the source-ordered policy operator catalog for ``dataset``."""

    try:
        return OPERATOR_CATALOGS[dataset]
    except KeyError as exc:
        raise ValueError(f"unsupported dataset: {dataset!r}") from exc


def bootstrap_operator_order_for(dataset: str) -> tuple[str, ...]:
    """Return fixed, non-policy bootstrap operators for ``dataset``."""

    try:
        return BOOTSTRAP_OPERATOR_ORDER[dataset]
    except KeyError as exc:
        raise ValueError(f"unsupported dataset: {dataset!r}") from exc


__all__ = [
    "BOOTSTRAP_OPERATOR_ORDER",
    "COST_RELIABILITY_REQUIREMENTS",
    "EARLY_STOP_OPERATOR",
    "EVALUATION_RELIABILITY_REQUIREMENTS",
    "FIRST_LAYER_EARLY_STOP_LOG_PROB_ADJUSTMENT",
    "FIRST_LAYER_EARLY_STOP_REPLACEMENT",
    "GENERATE_OPERATOR",
    "OPERATOR_CATALOGS",
    "OPERATOR_SAMPLING_WITH_REPLACEMENT",
    "OPERATOR_SELECTION_THRESHOLD",
    "POLICY_LAYER_COUNT",
    "POLICY_LOG_PROB_REDUCTION",
    "POLICY_LOSS_REDUCTION",
    "POLICY_LOSS_SIGN",
    "ROUTE_EXPANSION_ORDER",
    "TRAINING_SKIP_REASONS",
    "UTILITY_COST_COEFFICIENT",
    "bootstrap_operator_order_for",
    "operator_catalog_for",
]
