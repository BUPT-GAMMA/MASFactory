from masfactory.core.node import Node
from masfactory.core.gate import Gate
from masfactory.core.edge import Edge
from masfactory.adapters.model import Model
from typing import Callable
from masfactory.core.message import JsonMessageFormatter
from masfactory.components.graphs.base_graph import BaseGraph
from masfactory.components.graphs.internal_nodes import InternalGraphNode
from masfactory.components.agents.single_agent import SingleAgent
import inspect
import logging
from masfactory.core.node_template import NodeTemplate
from masfactory.utils.hook import masf_hook


class Loop(BaseGraph):
    """
    Iterative graph node with internal `Controller` and `TerminateNode`.

    Args:
        name: Loop name.
        max_iterations: Maximum iterations before forced termination.
        model: Optional model used by controller termination prompt.
        terminate_condition_prompt: Optional natural-language terminate condition.
        terminate_condition_function: Optional callable terminate condition.
        pull_keys: Keys pulled from outer attributes.
        push_keys: Keys pushed to outer attributes.
        attributes: Initial loop attributes.
        initial_messages: Initial cached controller messages.

    The loop supports cyclic execution only through the internal controller:
    internal nodes should feed back by `edge_to_controller`, not by direct inner cycles.
    """
    def __init__(self,
            name:str,
            max_iterations:int=10,
            model:Model|None=None,
            terminate_condition_prompt:str|None=None,
            terminate_condition_function:Callable|None=None,
            pull_keys:dict[str,dict|str]|None=None,
            push_keys:dict[str,dict|str]|None=None,
            attributes:dict[str,object] | None = None,
            initial_messages:dict[str,object] | None = None,
            edges: list[tuple[str, str] | tuple[str, str, dict[str, dict|str] ]]|None=None,
            nodes:list[tuple]|None=None,    
            build_func:Callable|None = None,
            ):
        """Create a Loop.

        Args:
            name: Loop name.
            max_iterations: Maximum iterations before forced termination.
            model: Optional model used by controller termination prompt.
            terminate_condition_prompt: Optional natural-language terminate condition.
            terminate_condition_function: Optional callable terminate condition. Supported signatures are:
                - `(input) -> terminate`
                - `(input, attributes) -> terminate`
                - `(input, attributes, controller) -> terminate`
                - `(input, attributes, controller, memories) -> terminate`
                - `(input, attributes, controller, memories, tools) -> terminate`
                - `(input, attributes, controller, memories, tools, retrievers) -> terminate`

                Where:
                - `input`: `dict[str, object]`
                - `attributes`: `dict[str, object]` (loop-local attribute store)
                - `controller`: internal controller node instance
                - `memories`: list of memories attached to the controller (may be empty)
                - `tools`: list of tools attached to the controller (may be empty)
                - `retrievers`: list of retrievers attached to the controller (may be empty)
                - `terminate`: `bool`
            pull_keys: Keys pulled from outer attributes.
            push_keys: Keys pushed to outer attributes.
            attributes: Initial loop attributes.
            initial_messages: Initial cached controller messages.
            edges: Optional declarative edge definitions for inner nodes.
            nodes: Optional declarative node definitions for inner nodes.
            build_func: Optional custom build function.
        """
        self._init_nodes = nodes
        self._init_edges = edges
        attributes = {} if attributes is None else dict(attributes)
        # Copy to avoid sharing mutable defaults and to avoid mutating caller-provided dicts.
        initial_messages = {} if initial_messages is None else dict(initial_messages)
        initial_messages_template = initial_messages.copy()

        # By default, expose loop iteration counters to the outer environment.
        if push_keys is None:
            push_keys = {
                'current_iteration': 'Current iteration of the loop.',
                'max_iterations': 'Maximum iterations of the loop.',
            }
        else:
            push_keys = dict(push_keys)
            # Respect explicit empty dict (push nothing).
            if len(push_keys) > 0:
                push_keys.setdefault('current_iteration', 'Current iteration of the loop.')
                push_keys.setdefault('max_iterations', 'Maximum iterations of the loop.')

        super().__init__(name, pull_keys, push_keys, attributes, build_func=build_func)
        self._attributes_store["current_iteration"] = 0
        self._attributes_store["max_iterations"] = max_iterations
        class TerminateNode(InternalGraphNode):
            """Internal node that forces loop termination (break-like behavior)."""
            def __init__(self, name, gate_close_callback:Callable|None=None, pull_keys:dict[str,dict|str]|None=None, push_keys:dict[str,dict|str]|None=None):
                super().__init__(name, gate_close_callback, pull_keys, push_keys)
            @property
            def is_ready(self) -> bool:
                for in_edge in self.in_edges:
                    if in_edge.is_congested:
                        return True
                return False
            @masf_hook(Node.Hook.FORWARD)
            def _forward(self,input:dict[str,object]) -> dict[str,object]:
                return input.copy() 
            # def _message_aggregate_in(self) -> dict[str,object]:
            #     input_msg:dict[str,object] = dict()
            #     for in_edge in self.in_edges:
            #         if in_edge.is_congested:
            #             message:dict[str,object] = in_edge.receive_message()
            #             input_msg = {**input_msg,**message}
            #     return input_msg
            def _message_dispatch_out(self,message:dict[str,object]):
                self._output = message
                self._gate = Gate.OPEN
        class Controller(InternalGraphNode):
            """Internal loop controller that decides continue vs terminate."""
            def __init__(self,
                name,
                max_iterations:int=10,
                model:Model|None=None,
                terminate_condition:str|None=None,
                terminate_condition_function:Callable|None=None,
                gate_close_callback:Callable|None=None,
                pull_keys:dict[str,dict|str]|None=None,
                push_keys:dict[str,dict|str]|None=None):
                """
                Args:
                    name: Controller name.
                    max_iterations: Maximum loop iterations.
                    model: Optional model used for termination checks.
                    terminate_condition: Optional natural-language terminate condition.
                    terminate_condition_function: Optional custom terminate function.
                """
                super().__init__(name, gate_close_callback, pull_keys, push_keys)

                self.outsource_input: dict[str,object] = {}
                self._message_cache: dict[str,object] = {}
                self._output: dict[str,object] = {}
                self._is_from_outside = True
                self._max_iterations = max_iterations
                self._terminate_condition_prompt = terminate_condition
                self._terminate_condition_function = terminate_condition_function
                self._terminate_condition_model = model
                self._current_iteration = 0
                self._terminated = False
                self._iteration_limited = self._max_iterations is not None and self._max_iterations > 0
                

                # Optional context objects for terminate_condition_function (may be empty).
                self._memories = []
                self._tools = []
                self._retrievers = []

                agent_terminate_condition_setting:bool = self._terminate_condition_model != None and self._terminate_condition_prompt != None

                if not agent_terminate_condition_setting and not self._iteration_limited and not self._terminate_condition_function:
                    raise ValueError("To avoid infinite loop, either terminate_condition_model and it's prompt or max_iterations or terminate_condition_function must be provided. ")
            def reset(self):
                """Reset controller runtime state."""
                self._is_from_outside = True
                self._current_iteration = 0
                self._terminated = False
                self.outsource_input = {}
                self._message_cache = initial_messages_template.copy()
                self._output = {}
                super().reset()
            def reset_gate(self):
                """Reset controller gate state."""
                self._is_from_outside = True
                self._current_iteration = 0
                self._terminated = False
                self.outsource_input = {}
                self._message_cache = initial_messages_template.copy()
                self._output = {}
                super().reset_gate()
            @property
            def terminated(self) -> bool:
                return self._terminated
            @masf_hook(Node.Hook.FORWARD)
            def _forward(self,input:dict[str,object]) -> dict[str,object]:
                self._current_iteration += 1
                self._attributes_store["current_iteration"] = self._current_iteration
                self._terminated = self._check_terminate(input)
                # If termination is triggered by the max-iteration guard, clamp the exposed
                # counter to max_iterations to avoid surfacing an off-by-one value to users.
                if (
                    self._iteration_limited
                    and self._max_iterations is not None
                    and self._current_iteration > self._max_iterations
                ):
                    self._current_iteration = self._max_iterations
                    self._attributes_store["current_iteration"] = self._current_iteration
                return input.copy()
            def _message_aggregate_in(self) -> dict[str,object]:           
                if self._is_from_outside:
                    input_msg = self.outsource_input
                    for input_key in self.input_keys:
                        if input_key not in self._message_cache:
                            self._message_cache[input_key] = "(not set yet)"
                    self._message_cache = {**self._message_cache,**input_msg}
                    self._is_from_outside = False
                    return self._message_cache.copy()
                else:
                    input_msg = super()._message_aggregate_in()
                    # input_msg = {}
                    # for in_edge in self.in_edges:
                    #     message = in_edge.receive_message()
                    #     input_msg = {**input_msg,**message}
                    self._message_cache = {**self._message_cache,**input_msg}
                    return self._message_cache.copy()
            def _terminate_condition_check(self,input:dict[str,object]) -> bool:
                """
                Evaluate termination conditions.

                - If `model` and `terminate_condition_prompt` are provided, evaluate by model.
                - If `terminate_condition_function` is provided, evaluate by callable.
                """
                terminate: bool = False

                if self._terminate_condition_model != None and self._terminate_condition_prompt != None:
                    condition_text = str(self._terminate_condition_prompt or "")
                    try:
                        condition_text = condition_text.format(**self._attributes_store, **input)
                    except Exception:
                        pass

                    system_prompt = (
                        "Your sole task is to determine if the [ANSWER] completely satisfies all criteria in the [CONDITION].\n"
                        "\n"
                        "If all criteria are met, your only output is the word: terminate\n"
                        "If even one criterion is not met, your only output is the word: continue\n"
                        "\n"
                        "Your evaluation must be strict. For example, if a condition requires \"under 50 words\", an answer with 51 words is a failure. If a condition requires JSON format, any syntax error is a failure. Do not add any explanations, notes, or any text besides 'terminate' or 'continue'.\n"
                    )
                    user_prompt = f"CONDITION:\n{condition_text}\n\nANSWER:\n{input}"

                    response_dict = self._terminate_condition_model.invoke(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        tools=None,
                    )

                    content = response_dict.get("content", "")
                    if isinstance(content, str):
                        terminate = ("terminate" in content.lower() or "stop" in content.lower())

                if self._terminate_condition_function:
                    param_count = len(inspect.signature(self._terminate_condition_function).parameters)
                    if param_count == 1:
                                    terminate = self._terminate_condition_function(input)
                    elif param_count == 2:
                                    terminate = self._terminate_condition_function(input, self._attributes_store)
                    elif param_count == 3:
                                    terminate = self._terminate_condition_function(input, self._attributes_store, self)
                    elif param_count == 4:
                                    terminate = self._terminate_condition_function(input, self._attributes_store, self, self._memories)
                    elif param_count == 5:
                                    terminate = self._terminate_condition_function(input, self._attributes_store, self, self._memories, self._tools)
                    elif param_count == 6:
                                    terminate = self._terminate_condition_function(
                                        input,
                                        self._attributes_store,
                                        self,
                                        self._memories,
                                        self._tools,
                                        self._retrievers,
                                    )
                    else:
                                    raise ValueError('terminate_condition_function must have at most 6 parameters')

                return terminate


            def _check_terminate(self,input:dict[str,object]) -> bool:
                """
                Return whether the loop should terminate.
                """
                iteration_hit_limit = self._iteration_limited and self._current_iteration > self._max_iterations
                condition_met = self._terminate_condition_check(input)
                return iteration_hit_limit or condition_met


            def _message_dispatch_out(self,message:dict[str,object]):
                if self._terminated:
                    self._output = message
                else:
                    self._output = message
                    for out_edge in self.out_edges:
                        out_edge.send_message(message)
                self._gate = Gate.OPEN
            def _close_out_edges(self):
                # super()._close_out_edges()
                # self._terminated = True
                pass
            
            def set_message_cache(self,message:dict[str,object]):
                self._message_cache = {**self._message_cache,**message}
        self._terminate_node = TerminateNode(self.name + "_terminate",self._close)
        self._controller = Controller(self.name + "_controller",max_iterations,model,terminate_condition_prompt,terminate_condition_function,self._close)
        self._terminate_node._set_owner(self)
        self._controller._set_owner(self)

    def _iter_internal_nodes(self) -> list[Node]:
        return [self._controller, self._terminate_node]

    def _label_internal_node(self, node: Node) -> str | None:
        if node is self._controller:
            return f"{self.name}.controller"
        if node is self._terminate_node:
            return f"{self.name}.terminate"
        return None

    def _close(self):
        self._gate = Gate.CLOSED
        self._close_out_edges()
    def edge_to_terminate_node(self,
            sender: Node,
            keys: dict[str,dict|str]|None=None):
        """Create an edge from an internal node to terminate node."""
        edge = Edge(sender, self._terminate_node, keys)
        self._edges.append(edge)
        sender.add_out_edge(edge)
        self._terminate_node.add_in_edge(edge)
        return edge
    def edge_to_controller(self,
            sender: Node,
            keys: dict[str,dict|str]|None=None):
        """Create a feedback edge from an internal node to controller."""
        edge = Edge(sender, self._controller, keys)
        self._edges.append(edge)
        sender.add_out_edge(edge)
        self._controller.add_in_edge(edge)
        return edge
    def edge_from_controller(self,
            receiver: Node,
            keys: dict[str,dict|str]|None=None):
        """Create an edge from controller to an internal node."""
        edge = Edge(self._controller, receiver, keys)
        self._edges.append(edge)
        self._controller.add_out_edge(edge)
        receiver.add_in_edge(edge)
        return edge
    @masf_hook(Node.Hook.FORWARD)
    def _forward(self,input:dict[str,object]) -> dict[str,object]:
        """Execute loop iterations until controller or terminate node stops it."""
        self.reset_gate()
        self._controller.outsource_input = input
        self._controller.execute(self._attributes_store)
        if self._controller.terminated:
            return self._controller.output.copy()   
        iteration_count = 0
        max_loop_iterations = 1000
        while self._gate == Gate.OPEN:
            iteration_count += 1
            if iteration_count > max_loop_iterations:
                logging.warning(f"Loop {self.name} exceeded max iterations ({max_loop_iterations})")
                break
            executed_any = False
            for node in self._nodes.values():
                if node.is_ready:
                    node.execute(self._attributes_store)
                    executed_any = True
                    break
            if self._controller.is_ready:
                self._controller.execute(self._attributes_store)
                executed_any = True
                if self._controller.terminated:
                    return self._controller.output.copy()
            if self._terminate_node.is_ready:
                self._terminate_node.execute(self._attributes_store)
                return self._terminate_node.output
            if not executed_any:
                return self._controller.output.copy() if self._controller.output else {}
        return self._controller.output.copy() if self._controller.output else {}
    def reset(self):
        super().reset()
        self._controller.reset()
        self._terminate_node.reset()
    def reset_gate(self):
        super().reset_gate()
        self._controller.reset_gate()
        self._terminate_node.reset_gate()
    @masf_hook(Node.Hook.BUILD)
    def build(self):
        """Build the loop by materializing declarative nodes/edges and building internal nodes.

        This supports a declarative style where `nodes=[...]` and `edges=[...]` define the loop
        body. It wires edges with special handling for the internal controller/terminate nodes,
        then builds the controller and terminate nodes, and finally calls `BaseGraph.build()`.

        The build is idempotent: calling `build()` multiple times is a no-op after the first
        successful build.
        """
        if self._is_built:
            return
        if self._init_nodes:
            for item in self._init_nodes:
                if len(item) < 2:
                    raise ValueError(f"Invalid node definition: {item}")
                name = item[0]
                target = item[1]
                others = item[2:]
                self.create_node(target, *others, name=name)

        if self._init_edges:
            for edge_def in self._init_edges:
                if len(edge_def) == 2:
                    src_name, dst_name = edge_def
                    keys = None
                elif len(edge_def) == 3:
                    src_name, dst_name, keys = edge_def
                else:
                    raise ValueError(f"Invalid edge definition: {edge_def}")
                src_token = str(src_name).strip()
                dst_token = str(dst_name).strip()
                src_key = src_token.lower()
                dst_key = dst_token.lower()
                if src_key in ["entry", "controller"]:
                    if dst_key in ["exit", "controller"]:
                        dst_node = self._controller
                    elif dst_key == "terminate":
                        dst_node = self._terminate_node
                    else:
                        dst_node = self._nodes.get(dst_token)
                        if dst_node is None:
                            raise ValueError(f"Destination node '{dst_name}' not found in loop '{self.name}'")
                    
                    if dst_key == "terminate":
                        self.edge_to_terminate_node(self._controller, keys)
                    else:
                        self.edge_from_controller(dst_node, keys)
                else:
                    src_node = self._nodes.get(src_token)
                    if src_node is None:
                        raise ValueError(f"Source node '{src_name}' not found in loop '{self.name}'")
                    if dst_key in ["exit", "controller"]:
                        self.edge_to_controller(src_node, keys)
                    elif dst_key == "terminate":
                        self.edge_to_terminate_node(src_node, keys)
                    else:
                        dst_node = self._nodes.get(dst_token)
                        if dst_node is None:
                            raise ValueError(f"Destination node '{dst_name}' not found in loop '{self.name}'")
                        self.create_edge(src_node, dst_node, keys)

        self._controller.build()
        self._terminate_node.build()
        super().build()
    def set_initial_messages(self,message:dict[str,object]):
        self._controller.set_message_cache(message)
