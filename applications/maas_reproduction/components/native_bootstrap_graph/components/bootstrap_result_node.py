"""Final deterministic reducer for the native bootstrap stage."""

from __future__ import annotations

from typing import Any

from masfactory.components.custom_node import CustomNode

from applications.maas_reproduction.maas_reproduction.schemas import (
    ArchitectureRequest,
    DispatchState,
    FailureSource,
    OperatorResult,
    RoutePlan,
)


class BootstrapResultNode(CustomNode):
    """Reduce bootstrap operator results into the canonical DispatchState."""

    def __init__(
        self,
        name: str = "BootstrapResultNode",
        *,
        dataset: str = "MATH",
        **kwargs: Any,
    ) -> None:
        self.dataset = dataset

        super().__init__(
            name,
            forward=self._forward_bootstrap,
            pull_keys={},
            push_keys={},
            **kwargs,
        )

    @staticmethod
    def _solution(
        result: OperatorResult | None,
    ) -> str | None:
        if result is None:
            return None

        if result.solution:
            return result.solution

        if result.candidates:
            return result.candidates[0]

        return result.code

    @staticmethod
    def _failure(
        message: str,
        *,
        stage: str = "bootstrap",
    ) -> dict[str, Any]:
        return {
            "stage": stage,
            "error_type": "bootstrap_failure",
            "message": message,
        }

    def _forward_bootstrap(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        request = data.get("request")
        route_plan = data.get("route_plan")
        programmer_result = data.get("programmer_result")
        generate_result = data.get("generate_result")
        bootstrap_error = data.get("bootstrap_error")

        if not isinstance(request, ArchitectureRequest):
            return {
                "dispatch_state": None,
                "failure_source": FailureSource.BOOTSTRAP.value,
                "error_state": self._failure(
                    "missing or invalid ArchitectureRequest",
                    stage="bootstrap",
                ),
            }

        if not isinstance(route_plan, RoutePlan):
            return {
                "dispatch_state": None,
                "failure_source": FailureSource.BOOTSTRAP.value,
                "error_state": self._failure(
                    "missing or invalid RoutePlan",
                    stage="bootstrap",
                ),
            }

        # Non-MATH datasets are explicitly outside this native bootstrap path.
        # The graph still returns a valid minimal state instead of creating
        # hidden business logic elsewhere.
        if self.dataset.lower() != "math":
            state = DispatchState(
                request=request,
                route_plan=route_plan,
                route_cursor=0,
                current_solution=None,
                candidates=(),
                termination_requested=False,
                error_state=None,
            )
            return {
                "dispatch_state": state,
                "failure_source": None,
                "error_state": None,
            }

        if bootstrap_error is not None:
            return {
                "dispatch_state": None,
                "failure_source": FailureSource.BOOTSTRAP.value,
                "error_state": bootstrap_error,
            }

        solution = (
            self._solution(generate_result)
            or self._solution(programmer_result)
        )

        if solution is None:
            return {
                "dispatch_state": None,
                "failure_source": FailureSource.BOOTSTRAP.value,
                "error_state": self._failure(
                    "bootstrap did not produce a usable solution"
                ),
            }

        state = DispatchState(
            request=request,
            route_plan=route_plan,
            route_cursor=0,
            current_solution=solution,
            candidates=(solution,),
            termination_requested=False,
            error_state=None,
        )

        return {
            "dispatch_state": state,
            "failure_source": None,
            "error_state": None,
        }


__all__ = ["BootstrapResultNode"]
