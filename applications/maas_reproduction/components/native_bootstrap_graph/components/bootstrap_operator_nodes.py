"""Bootstrap operator nodes for the native MaAS bootstrap stage."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from masfactory.components.custom_node import CustomNode

from applications.maas_reproduction.maas_reproduction.schemas import (
    ArchitectureRequest,
    OperatorResult,
    RoutePlan,
)


def _invoke_operator(operator: Any, payload: dict[str, Any]) -> Any:
    """Invoke an injected MASFactory-compatible operator."""
    if operator is None:
        raise RuntimeError("bootstrap operator is not configured")

    if hasattr(operator, "invoke"):
        result = operator.invoke(payload)
        if isinstance(result, tuple):
            return result[0]
        return result

    # Plain callables are accepted as an explicit test/injection seam. Runtime
    # production operators remain MASFactory nodes and use the shared Model.
    if callable(operator):
        return operator(payload)

    raise TypeError(
        "bootstrap operator must expose invoke() or be an injected callable"
    )


def _normalize_operator_result(
    value: Any,
    operator_name: str,
) -> OperatorResult:
    """Normalize a MASFactory operator response into OperatorResult."""
    if isinstance(value, OperatorResult):
        return value

    if isinstance(value, Mapping):
        data: Any = value

        if "operator_result" in data:
            data = data["operator_result"]

        if isinstance(data, OperatorResult):
            return data

        if not isinstance(data, Mapping):
            raise TypeError(
                f"{operator_name} returned invalid operator_result envelope"
            )

        payload = dict(data)
        payload.setdefault("operator_name", operator_name)
        payload.setdefault("status", "success")

        allowed = {
            "operator_name",
            "status",
            "solution",
            "candidates",
            "code",
            "execution_output",
            "metadata",
        }

        return OperatorResult(
            **{key: payload[key] for key in allowed if key in payload}
        )

    raise TypeError(
        f"{operator_name} did not return a valid OperatorResult"
    )


def _run_with_retry(
    operator: Any,
    operator_name: str,
    payload: dict[str, Any],
    retry_limit: int,
) -> OperatorResult:
    """Run an operator with bounded retry."""
    last_error: Exception | None = None

    for _attempt in range(retry_limit + 1):
        try:
            return _normalize_operator_result(
                _invoke_operator(operator, payload),
                operator_name,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    assert last_error is not None
    raise last_error


def _extract_solution(result: OperatorResult | None) -> str | None:
    """Extract the best available solution from an OperatorResult."""
    if result is None:
        return None

    if result.solution:
        return result.solution

    if result.candidates:
        return result.candidates[0]

    return result.code


class ProgrammerBootstrapNode(CustomNode):
    """Execute the native Programmer bootstrap operator."""

    def __init__(
        self,
        name: str = "ProgrammerBootstrapNode",
        *,
        operator: Any = None,
        retry_limit: int = 1,
        dataset: str = "MATH",
        **kwargs: Any,
    ) -> None:
        self.operator = operator
        self.retry_limit = retry_limit
        self.dataset = dataset

        super().__init__(
            name,
            forward=self._forward_programmer,
            pull_keys={},
            push_keys={},
            **kwargs,
        )

    def _forward_programmer(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        request = data.get("request")
        route_plan = data.get("route_plan")

        if not isinstance(request, ArchitectureRequest):
            return {
                "request": request,
                "route_plan": route_plan,
                "programmer_result": None,
                "bootstrap_error": {
                    "stage": "programmer",
                    "error_type": "invalid_request",
                    "message": "request is not an ArchitectureRequest",
                },
            }

        if not isinstance(route_plan, RoutePlan):
            return {
                "request": request,
                "route_plan": route_plan,
                "programmer_result": None,
                "bootstrap_error": {
                    "stage": "programmer",
                    "error_type": "invalid_route_plan",
                    "message": "route_plan is not a RoutePlan",
                },
            }

        if self.dataset.lower() != "math":
            return {
                "request": request,
                "route_plan": route_plan,
                "programmer_result": None,
                "bootstrap_error": None,
            }

        try:
            result = _run_with_retry(
                self.operator,
                "Programmer",
                {
                    "request": request,
                    "problem": request.problem,
                    "entry_point": request.entry_point,
                    "current_solution": "",
                },
                self.retry_limit,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "request": request,
                "route_plan": route_plan,
                "programmer_result": None,
                "bootstrap_error": {
                    "stage": "programmer",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            }

        return {
            "request": request,
            "route_plan": route_plan,
            "programmer_result": result,
            "bootstrap_error": None,
        }


class GenerateBootstrapNode(CustomNode):
    """Execute the native Generate refinement bootstrap operator."""

    def __init__(
        self,
        name: str = "GenerateBootstrapNode",
        *,
        operator: Any = None,
        retry_limit: int = 1,
        dataset: str = "MATH",
        **kwargs: Any,
    ) -> None:
        self.operator = operator
        self.retry_limit = retry_limit
        self.dataset = dataset

        super().__init__(
            name,
            forward=self._forward_generate,
            pull_keys={},
            push_keys={},
            **kwargs,
        )

    def _forward_generate(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        request = data.get("request")
        route_plan = data.get("route_plan")
        programmer_result = data.get("programmer_result")
        previous_error = data.get("bootstrap_error")

        if previous_error is not None:
            return {
                **data,
                "generate_result": None,
            }

        if self.dataset.lower() != "math":
            return {
                **data,
                "generate_result": None,
            }

        if not isinstance(request, ArchitectureRequest):
            return {
                **data,
                "generate_result": None,
                "bootstrap_error": {
                    "stage": "generate",
                    "error_type": "invalid_request",
                    "message": "request is not an ArchitectureRequest",
                },
            }

        solution = _extract_solution(programmer_result)

        if solution is None:
            return {
                **data,
                "generate_result": None,
                "bootstrap_error": {
                    "stage": "generate",
                    "error_type": "missing_bootstrap_solution",
                    "message": "Programmer did not produce a usable bootstrap solution",
                },
            }

        try:
            generated_result = _run_with_retry(
                self.operator,
                "Generate",
                {
                    "request": request,
                    "problem": request.problem,
                    "entry_point": request.entry_point,
                    "current_solution": solution,
                    "candidates": (solution,),
                },
                self.retry_limit,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                **data,
                "generate_result": None,
                "bootstrap_error": {
                    "stage": "generate",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            }

        return {
            **data,
            "generate_result": generated_result,
            "bootstrap_error": None,
        }


__all__ = [
    "ProgrammerBootstrapNode",
    "GenerateBootstrapNode",
]
