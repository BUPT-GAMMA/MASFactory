"""Native MASFactory architecture execution graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from masfactory.components.graphs.graph import Graph

from applications.maas_reproduction.maas_reproduction.contracts import operator_catalog_for

from .components.finalize_architecture_result_node import FinalizeArchitectureResultNode
from .components.initialize_execution_node import InitializeExecutionNode
from .components.route_planner_node import RoutePlannerNode
from ..attribute_firewall import assert_explicit_attribute_policies
from ..native_bootstrap_graph.workflow import NativeBootstrapGraph
from ..operator_dispatch_loop.workflow import OperatorDispatchLoop
from ..benchmark_completion_graph import BenchmarkCompletionGraph
from ..benchmark_completion_graph.humaneval_completion_graph import HumanEvalCompletionGraph


class ArchitectureExecGraph(Graph):
    """Compose initialization, planning, bootstrap, dispatch, and finalize seams.

    This graph deliberately has an empty attribute pull/push policy.  The evaluator
    is a sibling in the RootGraph, so evaluation-only context cannot be inherited.
    """

    def __init__(
        self,
        name: str = "architecture_exec",
        *,
        policy_controller: Any = None,
        operator_embeddings: Any = None,
        operator_catalog: Sequence[str] | None = None,
        programmer: Any = None,
        generate: Any = None,
        operator_registry: Mapping[str, Mapping[str, Any]] | None = None,
        dataset: str = "MATH",
        retry_limit: int = 1,
        max_dispatch_iterations: int = 100,
        cost_tracker: Any = None,
        humaneval_test_protocol: Any = None,
        humaneval_fallback: Any = None,
        graph_max_attempts: int = 1,
        **kwargs: Any,
    ) -> None:
        self.policy_controller = policy_controller
        self.operator_embeddings = operator_embeddings
        self.operator_catalog = tuple(operator_catalog or operator_catalog_for(dataset))
        self.programmer = programmer
        self.generate = generate
        self.operator_registry = dict(operator_registry or {})
        self.dataset = dataset
        self.retry_limit = retry_limit
        self.max_dispatch_iterations = max_dispatch_iterations
        self.cost_tracker = cost_tracker
        self.humaneval_test_protocol = humaneval_test_protocol
        self.humaneval_fallback = humaneval_fallback
        if isinstance(graph_max_attempts, bool) or not isinstance(graph_max_attempts, int) or graph_max_attempts < 1:
            raise ValueError("graph_max_attempts must be a positive integer")
        self.graph_max_attempts = graph_max_attempts
        super().__init__(name=name, pull_keys={}, push_keys={}, **kwargs)

    def build(self) -> None:
        if self._is_built:
            return

        initialize = self.create_node(
            InitializeExecutionNode,
            "initialize_execution",
        )
        planner = self.create_node(
            RoutePlannerNode,
            policy_controller=self.policy_controller,
            operator_embeddings=self.operator_embeddings,
            operator_catalog=self.operator_catalog,
            name="route_planner",
        )
        bootstrap = self.create_node(
            NativeBootstrapGraph,
            "native_bootstrap",
            programmer=self.programmer,
            generate=self.generate,
            retry_limit=self.retry_limit,
            dataset=self.dataset,
        )
        dispatch = self.create_node(
            OperatorDispatchLoop,
            "operator_dispatch_loop",
            operator_registry=self.operator_registry,
            max_iterations=self.max_dispatch_iterations,
        )
        if self.dataset == "HumanEval":
            completion = self.create_node(
                HumanEvalCompletionGraph,
                "benchmark_completion",
                protocol=self.humaneval_test_protocol,
                fallback_adapter=self.humaneval_fallback,
            )
        else:
            completion = self.create_node(
                BenchmarkCompletionGraph,
                "benchmark_completion",
                dataset=self.dataset,
            )
        finalize = self.create_node(
            FinalizeArchitectureResultNode,
            "finalize_architecture_result",
            cost_tracker=self.cost_tracker,
        )

        self.edge_from_entry(
            initialize,
            keys={"architecture_request": "Execution-only ArchitectureRequest."},
        )
        self.create_edge(
            initialize,
            planner,
            keys={"architecture_request": "Execution-only ArchitectureRequest."},
        )
        self.create_edge(
            planner,
            bootstrap,
            keys={
                "request": "Execution-only ArchitectureRequest.",
                "route_plan": "Policy RoutePlan.",
            },
        )
        self.create_edge(
            bootstrap,
            dispatch,
            keys={
                "dispatch_state": "Initial DispatchState.",
                "failure_source": "Bootstrap failure source.",
                "error_state": "Bootstrap error state.",
            },
        )
        self.create_edge(dispatch, completion, keys={
            "dispatch_state": "Final DispatchState.",
            "failure_source": "Execution failure source.",
            "error_state": "Execution error state.",
        })
        self.create_edge(completion, finalize, keys={
            "dispatch_state": "Final DispatchState.",
            "completion_result": "Benchmark-normalized completion.",
            "failure_source": "Execution failure source.",
            "error_state": "Execution error state.",
        })
        self.edge_to_exit(
            finalize,
            keys={"architecture_result": "Final execution-only ArchitectureResult."},
        )
        super().build()
        assert_explicit_attribute_policies(self)

    def _forward(self, input: dict[str, object]) -> dict[str, object]:
        """Capture a per-invocation cost baseline inside the execution subtree.

        ``cost_before`` is an explicit local attribute consumed only by the
        finalizer.  It is never put on an edge, controller message, route, or
        operator invocation.
        """
        if self.cost_tracker is not None:
            try:
                self._attributes_store["cost_before"] = self.cost_tracker.snapshot()
            except Exception as exc:  # finalizer reports unreliable cost
                self._attributes_store["cost_before"] = None
                self._attributes_store["cost_error"] = type(exc).__name__
        last_error: Exception | None = None
        for _attempt in range(1, self.graph_max_attempts + 1):
            try:
                return super()._forward(input)
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error


def build_architecture_exec_graph(**kwargs: Any) -> ArchitectureExecGraph:
    return ArchitectureExecGraph(**kwargs)


__all__ = ["ArchitectureExecGraph", "build_architecture_exec_graph"]
