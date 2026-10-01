"""Loop implementing Programmer's generate/parse/execute retry protocol."""
from __future__ import annotations
from typing import Any
from masfactory.components.controls.logic_switch import LogicSwitch
from masfactory.components.graphs.loop import Loop
from .components.code_generation_agent import CodeGenerationAgent
from .components.code_parse_node import CodeParseNode
from .components.programmer_execution_node import ProgrammerExecutionNode
from .components.programmer_result_node import ProgrammerResultNode
from .components.retry_decision_node import RetryDecisionNode
from ...attribute_firewall import seal_loop_attributes


class ProgrammerRetryLoop(Loop):
    """Bounded internal control flow; retry never leaks into dispatch state."""
    def __init__(self, name: str = "ProgrammerRetryLoop", *, generator: Any = None,
                 executor: Any = None, max_attempts: int = 3) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        self.generator, self.executor, self.max_attempts = generator, executor, max_attempts
        super().__init__(name, max_iterations=max_attempts + 1,
                         terminate_condition_function=lambda *_args: False,
                         pull_keys={}, push_keys={})
        seal_loop_attributes(self)

    def build(self) -> None:
        if self._is_built: return
        generate = self.create_node(CodeGenerationAgent, "CodeGenerationAgent", generator=self.generator)
        parse = self.create_node(CodeParseNode, "CodeParseNode")
        execute = self.create_node(ProgrammerExecutionNode, "ProgrammerExecutionNode", executor=self.executor)
        decide = self.create_node(RetryDecisionNode, "RetryDecisionNode", max_attempts=self.max_attempts)
        result = self.create_node(ProgrammerResultNode, "ProgrammerResultNode")
        switch = self.create_node(LogicSwitch, "ProgrammerLogicSwitch", routes={
            result.name: lambda message, _attrs: not bool(message.get("retry_requested")),
            self._controller.name: lambda message, _attrs: bool(message.get("retry_requested")),
        })
        # LogicSwitch is a MASFactory control component whose defaults are
        # ``None`` (inherit all attributes).  This retry loop is an explicit
        # firewall, so keep its control node attribute-free as well.
        switch.set_pull_keys({})
        switch.set_push_keys({})

        self.edge_from_controller(generate, {"operator_invocation": "Operator invocation.",
                                             "feedback": "Execution feedback.", "attempt": "Attempt number."})
        self.create_edge(generate, parse, {"operator_invocation": "Operator invocation.",
                                           "attempt": "Attempt number.", "code": "Generated code.",
                                           "generation_error": "Generation error."})
        self.create_edge(parse, execute, {"operator_invocation": "Operator invocation.",
                                          "attempt": "Attempt number.",
                                          "code": "Generated code.", "parse_error": "Parse error."})
        self.create_edge(execute, decide, {"operator_invocation": "Operator invocation.",
                                           "attempt": "Attempt number.",
                                           "code": "Generated code.", "parse_error": "Parse error.",
                                           "execution_success": "Execution success.",
                                           "execution_output": "Execution output.",
                                           "feedback": "Execution feedback."})
        self.create_edge(decide, switch, {"operator_invocation": "Operator invocation.",
                                          "code": "Generated code.", "execution_success": "Execution success.",
                                          "execution_output": "Execution output.", "feedback": "Execution feedback.",
                                          "retry_requested": "Retry control flag.", "attempt": "Attempt number."})
        self.create_edge(switch, result, {"code": "Generated code.", "execution_success": "Execution success.",
                                          "execution_output": "Execution output.", "attempt": "Attempt number."})
        self.edge_to_terminate_node(result, {"operator_result": "Structured OperatorResult."})
        self.edge_to_controller(switch, {"operator_invocation": "Operator invocation.",
                                         "feedback": "Execution feedback.", "attempt": "Attempt number."})
        super().build()


__all__ = ["ProgrammerRetryLoop"]
