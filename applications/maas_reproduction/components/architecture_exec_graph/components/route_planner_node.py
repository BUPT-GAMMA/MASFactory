"""The sole policy-decision node for the native MaAS execution graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from masfactory.components.custom_node import CustomNode

from applications.maas_reproduction.maas_reproduction.contracts import (
    EARLY_STOP_OPERATOR,
    FIRST_LAYER_EARLY_STOP_LOG_PROB_ADJUSTMENT,
    GENERATE_OPERATOR,
)
from applications.maas_reproduction.maas_reproduction.schemas import ArchitectureRequest, FailureSource, RouteItem, RoutePlan


class RoutePlannerNode(CustomNode):
    """Call the policy controller and expose one immutable, flattened route.

    The controller and embeddings are constructor dependencies.  They never
    cross the graph edge or become execution state.  ``replay_routes`` is a
    test-mode seam: when supplied, the recorded layer selections are used and
    the policy controller is not called.
    """

    def __init__(
        self,
        *args: Any,
        policy_controller: Any = None,
        operator_embeddings: Any = None,
        operator_catalog: Sequence[str] | None = None,
        replay_routes: Mapping[int, Sequence[Sequence[str] | Sequence[int]]] | None = None,
        replay_policy_log_probs: Mapping[int, Any] | None = None,
        name: str = "route_planner",
    ) -> None:
        # MASFactory create_node supplies the node name as the first positional
        # argument, while direct unit tests historically supplied the three
        # planner dependencies positionally.  Accept both forms explicitly.
        positional = list(args)
        if positional and isinstance(positional[0], str):
            name = positional.pop(0)
        if positional:
            if policy_controller is not None:
                raise TypeError("policy_controller supplied twice")
            policy_controller = positional.pop(0)
        if positional:
            if operator_embeddings is not None:
                raise TypeError("operator_embeddings supplied twice")
            operator_embeddings = positional.pop(0)
        if positional:
            if operator_catalog is not None:
                raise TypeError("operator_catalog supplied twice")
            operator_catalog = positional.pop(0)
        if positional:
            raise TypeError("unexpected positional RoutePlannerNode arguments")
        if operator_catalog is None:
            raise ValueError("operator_catalog is required")
        catalog = tuple(operator_catalog)
        if not catalog or any(not isinstance(item, str) or not item for item in catalog):
            raise ValueError("operator_catalog must contain non-empty names")
        if GENERATE_OPERATOR not in catalog:
            raise ValueError("operator_catalog must contain Generate")
        self.policy_controller = policy_controller
        self.operator_embeddings = operator_embeddings
        self.operator_catalog = catalog
        self.replay_routes = replay_routes
        self.replay_policy_log_probs = replay_policy_log_probs or {}
        super().__init__(name=name, forward=self._plan, pull_keys={}, push_keys={})

    def _plan(self, input_data: dict[str, object]) -> dict[str, object]:
        request = input_data.get("architecture_request", input_data.get("request"))
        if isinstance(request, Mapping):
            request = ArchitectureRequest(**dict(request))
        if not isinstance(request, ArchitectureRequest):
            return self._failure("architecture_request is required", request=request)

        try:
            replay = self.replay_routes is not None
            if replay:
                if request.problem_index not in self.replay_routes:  # type: ignore[operator]
                    raise ValueError("no replay route for problem_index")
                selected_layers = self.replay_routes[request.problem_index]  # type: ignore[index]
                log_probs_layers = []
                policy_log_prob = self.replay_policy_log_probs.get(request.problem_index)
                if policy_log_prob is None:
                    policy_log_prob = self._zero_log_prob()
                first_layer = tuple(selected_layers[0]) if selected_layers else ()
                first_names = [self.operator_catalog[x] if isinstance(x, int) else x for x in first_layer]
                if any(name.lower() == EARLY_STOP_OPERATOR.lower() for name in first_names):
                    policy_log_prob = policy_log_prob + self._constant_like(
                        policy_log_prob, FIRST_LAYER_EARLY_STOP_LOG_PROB_ADJUSTMENT
                    )
            else:
                result = self.policy_controller.forward(
                    request.problem, self.operator_embeddings, self.operator_catalog
                )
                if not isinstance(result, Sequence) or len(result) != 2:
                    raise ValueError("policy controller must return (log_probs_layers, raw_selected_layers)")
                log_probs_layers, selected_layers = result
                selected_layers = selected_layers
                policy_log_prob = self._aggregate_log_probs(log_probs_layers)
                selected_layers = tuple(selected_layers)
                # The source controller replaces a first-layer EarlyStop with
                # Generate and applies this deterministic adjustment.
                first_layer = tuple(selected_layers[0]) if selected_layers else ()
                first_names = [self.operator_catalog[x] if isinstance(x, int) else x for x in first_layer]
                if any(name.lower() == EARLY_STOP_OPERATOR.lower() for name in first_names):
                    policy_log_prob = policy_log_prob + self._constant_like(
                        policy_log_prob, FIRST_LAYER_EARLY_STOP_LOG_PROB_ADJUSTMENT
                    )
            items = self._flatten(selected_layers)
            if replay and self.replay_policy_log_probs.get(request.problem_index) is None:
                policy_log_prob = self._aggregate_log_probs(log_probs_layers) if log_probs_layers else policy_log_prob
            return {
                "architecture_request": request,
                # Internal bootstrap nodes historically call this field ``request``;
                # it is the same execution-only object and contains no answer key.
                "request": request,
                "route_plan": RoutePlan(items=items, policy_log_prob=policy_log_prob),
            }
        except Exception as exc:  # planning failure is structured; never fabricate a RoutePlan
            return self._failure(str(exc), request=request)

    def _flatten(self, selected_layers: Sequence[Sequence[str] | Sequence[int]]) -> tuple[RouteItem, ...]:
        flattened: list[RouteItem] = []
        for layer_index, raw_layer in enumerate(selected_layers):
            names = [self.operator_catalog[item] if isinstance(item, int) else item for item in raw_layer]
            if any(name not in self.operator_catalog for name in names):
                raise ValueError("policy selected an unknown operator")
            if layer_index == 0:
                if any(name.lower() == EARLY_STOP_OPERATOR.lower() for name in names):
                    names = [GENERATE_OPERATOR]
                elif not any("generate" in name.lower() for name in names):
                    names = [GENERATE_OPERATOR]
                elif "generate" not in names[0].lower():
                    generate_at = next(
                        i for i, name in enumerate(names)
                        if "generate" in name.lower()
                    )
                    names = [names[generate_at], *names[:generate_at], *names[generate_at + 1 :]]
            for position, name in enumerate(names):
                flattened.append(RouteItem(len(flattened), layer_index, position, name,
                                           is_control_marker=name == EARLY_STOP_OPERATOR))
            if layer_index > 0 and any(name == EARLY_STOP_OPERATOR for name in names):
                break
        return tuple(flattened)

    @staticmethod
    def _aggregate_log_probs(values: Sequence[Any]) -> Any:
        if not values:
            return RoutePlannerNode._zero_log_prob()
        # Controllers normally return one already-reduced Tensor per layer;
        # accepting a per-selection sequence as well keeps the seam explicit.
        reduced = []
        for value in values:
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                value = RoutePlannerNode._aggregate_log_probs(value)
            reduced.append(value)
        total = reduced[0]
        for value in reduced[1:]:
            total = total + value
        return total

    @staticmethod
    def _zero_log_prob() -> Any:
        try:
            import torch
            return torch.tensor(0.0)
        except ImportError:
            return 0.0

    @staticmethod
    def _constant_like(value: Any, number: float) -> Any:
        try:
            import torch
            if isinstance(value, torch.Tensor):
                return torch.as_tensor(number, dtype=value.dtype, device=value.device)
        except ImportError:
            pass
        return number

    @staticmethod
    def _failure(error: str, request: Any = None) -> dict[str, object]:
        return {"architecture_request": request, "request": request,
                "route_plan": None, "policy_log_prob": None,
                "failure_source": FailureSource.PLANNING,
                "result_valid": False, "planning_error": error}


__all__ = ["RoutePlannerNode"]
