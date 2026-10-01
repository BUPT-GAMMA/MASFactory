"""Native Programmer graph and its bounded retry subgraph."""
from __future__ import annotations
from typing import Any
from masfactory.components.graphs.graph import Graph
from .programmer_retry_loop import ProgrammerRetryLoop


class ProgrammerGraph(Graph):
    """Expose the Programmer operator as ``OperatorInvocation -> OperatorResult``."""
    def __init__(self, name: str = "Programmer", *, code_generator: Any = None,
                 programmer: Any = None, executor: Any = None, max_attempts: int = 3) -> None:
        super().__init__(name, pull_keys={}, push_keys={})
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        self.generator = code_generator if code_generator is not None else programmer
        self.executor, self.max_attempts = executor, max_attempts

    def build(self) -> None:
        if self._is_built: return
        retry_loop = self.create_node(
            ProgrammerRetryLoop, "ProgrammerRetryLoop", generator=self.generator,
            executor=self.executor, max_attempts=self.max_attempts,
        )
        self.edge_from_entry(retry_loop, {"operator_invocation": "OperatorInvocation or mapping."})
        self.edge_to_exit(retry_loop, {"operator_result": "Structured OperatorResult."})
        super().build()


__all__ = ["ProgrammerGraph"]
