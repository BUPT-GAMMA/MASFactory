"""Native bootstrap graph for the MaAS execution pipeline.

The graph is intentionally limited to orchestration:
    ProgrammerBootstrapNode
        -> GenerateBootstrapNode
        -> BootstrapResultNode

Business execution, retry, normalization, and deterministic reduction are
implemented behind explicit node interfaces.
"""

from __future__ import annotations

from typing import Any

from masfactory.components.graphs.graph import Graph

from .components.bootstrap_operator_nodes import (
    GenerateBootstrapNode,
    ProgrammerBootstrapNode,
)
from .components.bootstrap_result_node import BootstrapResultNode


class NativeBootstrapGraph(Graph):
    """Native MATH bootstrap graph.

    Contract:
        ArchitectureRequest + RoutePlan
            -> initial DispatchState / structured bootstrap failure

    Responsibilities of this Graph:
        - create nodes
        - connect nodes
        - declare message contracts
        - expose the graph interface

    It does not:
        - execute operators directly
        - call provider SDKs
        - calculate score/cost/utility
        - access policy controller
        - access expected_answer
        - perform optimization
    """

    def __init__(
        self,
        name: str = "NativeBootstrapGraph",
        *,
        programmer: Any = None,
        generate: Any = None,
        retry_limit: int = 1,
        dataset: str = "MATH",
    ) -> None:
        if isinstance(retry_limit, bool):
            raise ValueError("retry_limit must be a non-negative integer")
        if not isinstance(retry_limit, int) or retry_limit < 0:
            raise ValueError("retry_limit must be a non-negative integer")

        self.programmer = programmer
        self.generate = generate
        self.retry_limit = retry_limit
        self.dataset = dataset

        super().__init__(name, pull_keys={}, push_keys={})

    def build(self) -> None:
        if self._is_built:
            return

        programmer_node = self.create_node(
            ProgrammerBootstrapNode,
            "ProgrammerBootstrapNode",
            operator=self.programmer,
            retry_limit=self.retry_limit,
            dataset=self.dataset,
        )

        generate_node = self.create_node(
            GenerateBootstrapNode,
            "GenerateBootstrapNode",
            operator=self.generate,
            retry_limit=self.retry_limit,
            dataset=self.dataset,
        )

        result_node = self.create_node(
            BootstrapResultNode,
            "BootstrapResultNode",
            dataset=self.dataset,
        )

        # Root input -> Programmer
        self.edge_from_entry(
            programmer_node,
            {
                "request": "Architecture request.",
                "route_plan": "Already selected RoutePlan.",
            },
        )

        # Programmer -> Generate
        self.create_edge(
            programmer_node,
            generate_node,
            {
                "request": "Architecture request.",
                "route_plan": "Already selected RoutePlan.",
                "programmer_result": "Structured Programmer OperatorResult.",
                "bootstrap_error": "Structured Programmer bootstrap error or None.",
            },
        )

        # Generate -> Result
        self.create_edge(
            generate_node,
            result_node,
            {
                "request": "Architecture request.",
                "route_plan": "Already selected RoutePlan.",
                "programmer_result": "Structured Programmer OperatorResult or None.",
                "generate_result": "Structured Generate OperatorResult or None.",
                "bootstrap_error": "Structured bootstrap error or None.",
            },
        )

        # Result -> graph exit
        self.edge_to_exit(
            result_node,
            {
                "dispatch_state": "Initial canonical DispatchState or None.",
                "failure_source": "Bootstrap failure source or None.",
                "error_state": "Structured bootstrap error state or None.",
            },
        )

        super().build()


def build_native_bootstrap_graph(**kwargs: Any) -> NativeBootstrapGraph:
    """Construct a native bootstrap graph without invoking it."""
    return NativeBootstrapGraph(**kwargs)


__all__ = [
    "NativeBootstrapGraph",
    "build_native_bootstrap_graph",
]
