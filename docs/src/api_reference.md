# API Reference

This document provides a complete API reference for the MASFactory framework, including detailed descriptions of all core classes, methods, and interfaces.

::: tip Usage Guide
- Click the left navigation bar to quickly locate the corresponding module
- Each class includes detailed constructor parameter descriptions and usage examples
- Method parameters and return values have complete type annotations
- Use <kbd>Ctrl</kbd> + <kbd>F</kbd> to quickly search for specific APIs
:::

::: info Version Information
This document corresponds to MASFactory v1.0.2
:::

## Core Modules

The core modules contain the basic components of the MASFactory framework, which are essential components for building any workflow.

### Node Class {#node-class}

::: info Base Node Class
Node is the abstract base class for all computing units in MASFactory, providing basic functionality for node variable management, message passing, and execution control.
:::

```python
class Node(ABC):
    def __init__(self,
                name: str,
                pull_keys: dict[str,dict|str] | None = None,
                push_keys: dict[str,dict|str] | None = None,
                attributes: dict[str,object] | None = None)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `name` | `str` | - | Node name, used to identify this node in logs |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | Node variable keys and descriptions extracted from outer Graph |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | Node variable keys and descriptions written back to outer node after execution |
| `attributes` | `dict[str,object] \| None` | `None` | Initial node variables of the node |

#### Important Properties

| Property | Type | Description |
|------|------|------|
| `name` | `str` | Node name (read-only) |
| `in_edges` | `list[Edge]` | List of all incoming edges (read-only) |
| `out_edges` | `list[Edge]` | List of all outgoing edges (read-only) |
| `input_keys` | `dict[str,dict\|str]` | Merged result of all incoming edge keys (read-only) |
| `output_keys` | `dict[str,dict\|str]` | Merged result of all outgoing edge keys (read-only) |
| `is_ready` | `bool` | Check if the node is ready for execution (read-only) |
| `gate` | `Gate` | Open/closed state of the node (read-only) |

#### Core Methods

##### execute()

```python
def execute(self, outer_env: dict[str,object] | None = None) -> None
```

Execute the complete process of the node.

**Execution Steps:**
1. Update node variables
2. Aggregate input messages from all incoming edges
3. Call `_forward` method to process input
4. Distribute output to all outgoing edges
5. Update node variables

**Parameters:**
- `outer_env`: Node variables of the external environment

##### _forward() *[Abstract Method]*

```python
@abstractmethod
def _forward(self, input: dict[str,object]) -> dict[str,object]
```

Core computation logic of the node, must be implemented by subclasses.

**Parameters:**
- `input`: Dictionary payload aggregated from incoming edges

**Returns:**
- `dict[str,object]`: Dictionary payload to be dispatched to outgoing edges

::: warning Node Variable Processing Rules
- `pull_keys` is None: Inherit all node variables from outer node
- `pull_keys` is not None: Extract according to specified fields from outer node variables
- `pull_keys` is empty dict: Do not inherit any outer node variables
:::

---

### Edge Class

::: info Edge Connection Class
Edge connects two Nodes and is responsible for flow control and message passing.
:::

```python
class Edge:
    def __init__(self,
                sender: Node,
                receiver: Node,
                keys: dict[str,dict|str] | None = None)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `sender` | `Node` | - | Node that sends messages |
| `receiver` | `Node` | - | Node that receives messages |
| `keys` | `dict[str,dict\|str] \| None` | `None` | Message field mapping; defaults to `{\"message\": \"\"}` |

#### Important Properties

| Property | Type | Description |
|------|------|------|
| `keys` | `dict[str,dict\|str]` | Key description mapping of the edge (read-only) |
| `is_congested` | `bool` | Check if the edge is congested (has unreceived messages) (read-only) |
| `gate` | `Gate` | Open/closed state of the edge (read-only) |

#### Core Methods

##### send_message()

```python
def send_message(self, message: dict[str,object]) -> None
```

Send message to the edge, waiting for the receiving node to retrieve.

**Parameters:**
- `message`: Message dictionary to send

**Exceptions:**
- `RuntimeError`: If the edge is already congested
- `KeyError`: If any required key in `edge.keys` is missing in `message`

##### receive_message()

```python
def receive_message() -> dict[str,object]
```

Receive message from the edge and clear congestion status.

**Returns:**
- `dict[str,object]`: Received message dictionary

**Exceptions:**
- `RuntimeError`: If the edge is not congested

---

### MessageFormatter Class

::: info Message Formatter Base Class
MessageFormatter is the abstract base class for all message formatters. It is responsible for two things:
- parsing model output text into a structured `dict`
- rendering a structured `dict` into prompt text

The public API no longer exposes message objects such as `Message` or `JsonMessage`; the framework now uses `dict` as the unified message carrier.
:::

```python
class MessageFormatter(ABC):
    def __init__(self)
```

#### Core Methods

##### format() *[Abstract Method]*

```python
@abstractmethod
def format(self, message: str) -> dict
```

Parse raw model output text into a structured `dict`.

**Parameters:**
- `message`: Raw message string

**Returns:**
- `dict`: Parsed structured result

**Exceptions:**
- `NotImplementedError`: Subclasses must implement this method

##### dump() *[Abstract Method]*

```python
@abstractmethod
def dump(self, message: dict) -> str
```

Render a structured `dict` into model input text.

**Parameters:**
- `message`: Structured message dictionary

**Returns:**
- `str`: Rendered text

::: tip Note
`MessageFormatter` itself is not a singleton. Only stateless formatter implementations such as `StatelessFormatter` use a shared-instance strategy.
:::

---

### JsonMessageFormatter Class

::: info JSON Message Formatter
JsonMessageFormatter is a strict JSON formatter. It parses model output into a `dict`, and serializes a `dict` back into JSON text.
:::

```python
class JsonMessageFormatter(MessageFormatter):
    def __init__(self)
```

#### Core Methods

##### format()

```python
def format(self, message: str) -> dict
```

Parse a JSON object from model output and return it as a `dict`.

**Parameters:**
- `message`: JSON string message

**Returns:**
- `dict`: Parsed JSON object

**Exceptions:**
- `ValueError`: Raised when no valid JSON object can be parsed from the message

**Features:**
- Tries to remove code fences and extract the outermost JSON substring
- Applies limited repair for malformed JSON before failing
- Always returns a `dict`

##### dump()

```python
def dump(self, message: dict) -> str
```

Serialize a structured `dict` to a JSON string.

**Parameters:**
- `message`: Structured message dictionary

**Returns:**
- `str`: JSON text

## Component Modules

### Agent Class

::: info Agent Node
Agent is the basic computational unit in the graph, encapsulating large language models, instructions, tools, and memory modules.
:::

```python
class Agent(Node):
    def __init__(
        self,
        name: str,
        instructions: str | list[str],
        *,
        model: Model,
        formatters: list[MessageFormatter] | MessageFormatter | None = None,
        max_retries: int | None = 3,
        retry_delay: int | None = 1,
        retry_backoff: int | None = 2,
        prompt_template: str | list[str] | None = None,
        tools: list[Callable] | None = None,
        memories: list[Memory] | None = None,
        retrievers: list[Retrieval] | None = None,
        skills: list[Skill] | None = None,
        pull_keys: dict[str, dict|str] | None = {},
        push_keys: dict[str, dict|str] | None = {},
        model_settings: dict | None = None,
        role_name: str | None = None,
        attributes: dict[str, object] | None = None,
        hide_unused_fields: bool = False,
        reuse_attachment_tags: bool = True,
    )
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `name` | `str` | - | Unique identifier of Agent in the graph |
| `instructions` | `str \| list[str]` | - | Agent instructions defining its behavior and tasks |
| `model` | `Model` | - | Model adapter used to drive the Agent (required, keyword-only) |
| `formatters` | `MessageFormatter \| list[MessageFormatter] \| None` | `None` | Input/output formatters (single = shared; two = `[in, out]`) |
| `max_retries` | `int \| None` | `3` | Maximum retries for model calls |
| `retry_delay` | `int \| None` | `1` | Base delay multiplier for exponential backoff retries |
| `retry_backoff` | `int \| None` | `2` | Exponential backoff base |
| `prompt_template` | `str \| list[str] \| None` | `None` | Prompt template |
| `tools` | `list[Callable] \| None` | `None` | List of tool functions |
| `memories` | `list[Memory] \| None` | `None` | List of memory adapters; at most one `HistoryProvider`-backed memory may be attached |
| `retrievers` | `list[Retrieval] \| None` | `None` | Retrieval adapters (RAG/MCP, etc.) |
| `skills` | `list[Skill] \| None` | `None` | Explicitly loaded skill packages attached at the directive layer |
| `pull_keys` | `dict[str,dict|str] \| None` | `{}` | Visible/required node variable keys and descriptions |
| `push_keys` | `dict[str,dict|str] \| None` | `{}` | Node variable keys and descriptions written back after execution |
| `model_settings` | `dict \| None` | `None` | Additional parameters passed to the model |
| `role_name` | `str` | `None` | Role name of the Agent |
| `attributes` | `dict[str,object] \| None` | `None` | Initial local attributes for the agent |
| `hide_unused_fields` | `bool` | `False` | Whether to omit unused fields when formatting prompts |
| `reuse_attachment_tags` | `bool` | `True` | Deduplicate same-turn media; if rich history media blocks are available, matching attachments may reuse those existing tags |

#### Supported model_settings Parameters

| Parameter | Type | Range | Description |
|------|------|------|------|
| `temperature` | `float` | [0.0, 2.0] | Temperature parameter controlling output randomness |
| `max_tokens` | `int` | - | Maximum number of output tokens |
| `top_p` | `float` | [0.0, 1.0] | Nucleus sampling parameter |
| `stop` | `list[str]` | - | List of tokens to stop generation |
| `tool_choice` | `str \| dict` | provider-specific | Tool routing mode or provider-native tool choice payload |

#### Usage Example

```python
agent = Agent(
    name="writer",
    model=model,
    instructions="Write concise JSON answers",
    tools=[web_search],
    memories=[conversation_memory],
    pull_keys={"topic": "Current topic"},
    push_keys={"last_answer": "Latest answer"}
)
```

::: tip Tool Call Handling
When tools are provided, the model may produce tool call responses. Agent will automatically call and backfill results, then ask the model again until final content is returned.
:::

::: info Invocation assembly
`Agent.observe(...)` delegates prompt/message/tool assembly to `RequestAssembler`.
The runtime keeps directives (instructions + skills), conversation history, passive resource context, and actions/tools as separate semantic layers.
:::

---

### BaseGraph Class

::: info Base Graph Class
BaseGraph is the foundation for all graph types, providing basic functionality for node management and edge connections.
:::

```python
class BaseGraph(Node):
    def __init__(self, 
                name: str, 
                pull_keys: dict[str,dict|str] | None = None, 
                push_keys: dict[str,dict|str] | None = None,
                attributes: dict[str,object] | None = None,
                build_func: Callable | None = None)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `name` | `str` | - | Name of the graph, used to identify this graph |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | Node variable keys and descriptions extracted from outer layer |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | Node variable keys and descriptions written back after execution |
| `attributes` | `dict[str,object] \| None` | `None` | Initial node variables of the graph |
| `build_func` | `Callable \| None` | `None` | Optional build callback executed before child `build()` (signature: `(graph: BaseGraph) -> None`) |

#### Core Methods

##### create_node()

```python
def create_node(self, cls: type[Node] | NodeTemplate, *args, **kwargs) -> Node
```

Create a new node in the graph.

**Parameters:**
- `cls`: Type of node to create, must be a subclass of Node
- `*args`: Positional arguments passed to node constructor
- `**kwargs`: Keyword arguments passed to node constructor

**Returns:**
- `Node`: Created node instance

**Exceptions:**
- `TypeError`: If `cls` is not a `Node` subclass or `NodeTemplate`
- `ValueError`: If the node name is invalid/duplicated, or if the type is restricted (RootGraph / SingleAgent)

**Restrictions:**
- Cannot create RootGraph type nodes
- Cannot create SingleAgent type nodes

##### create_edge()

```python
def create_edge(self,
               sender: Node,
               receiver: Node,
               keys: dict[str, dict|str] | None = None) -> Edge
```

Create an edge between two nodes.

**Parameters:**
- `sender`: Node that sends messages
- `receiver`: Node that receives messages
- `keys`: Key dictionary defining message field mapping

**Returns:**
- `Edge`: Created edge instance

**Exceptions:**
- `ValueError`: If nodes are not in the graph, or creating edge would form cycles or duplicate edges

**Safety Checks:**
- Loop detection
- Duplicate edge detection

##### build()

```python
def build() -> None
```

Build the graph and all its child nodes.

##### check_built()

```python
def check_built() -> bool
```

Check if the graph is built.

**Returns:**
- `bool`: Returns True if the graph and all its child nodes are built

---

### LogicSwitch Class {#logic-switch-class}

::: info Logic Branch Node
LogicSwitch is a node that routes input to different output edges based on conditions, similar to switch statements in programming languages.
:::

```python
class LogicSwitch(Node):
    def __init__(self, 
                name: str, 
                pull_keys: dict[str,dict|str] | None = None, 
                push_keys: dict[str,dict|str] | None = None,
                attributes: dict[str,object] | None = None,
                routes: dict[str, Callable[[dict, dict[str,object]], bool]] | None = None)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `name` | `str` | - | Name of the node |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | Node variable keys and descriptions extracted from outer layer |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | Node variable keys and descriptions written back after execution |
| `attributes` | `dict[str,object] \| None` | `None` | Initial local attributes for this node |
| `routes` | `dict[str, Callable] \| None` | `None` | Optional declarative routes: `{receiver_node_name: predicate}` (compiled during `build()`) |

#### Core Methods

##### condition_binding() {#logic-switch-binding}

```python
def condition_binding(self, 
                     condition: Callable[[dict, dict[str,object]], bool], 
                     out_edge: Edge) -> None
```

Bind an output edge with a condition callback function.

**Parameters:**
- `condition`: Function that receives the aggregated input message (dict) and node attributes (dict) and returns a boolean
- `out_edge`: Output edge to associate with the condition

**Exceptions:**
- `ValueError`: If the edge is already bound
- `ValueError`: If out_edge is not in the node's output edges

#### Usage Example

```python
# Create logic switch
switch = graph.create_node(LogicSwitch, "content_router")

# Create two target nodes
positive_handler = graph.create_node(Agent, 
    name="positive_handler",
    model=model,
    instructions="Handle positive content"
)

negative_handler = graph.create_node(Agent,
    name="negative_handler", 
    model=model,
    instructions="Handle negative content"
)

# Create output edges
e1 = graph.create_edge(switch, positive_handler, {"content": "Content"})
e2 = graph.create_edge(switch, negative_handler, {"content": "Content"})

# Bind conditions
switch.condition_binding(
    lambda message, attrs: "positive" in str(message.get("content", "")).lower(), 
    e1
)
switch.condition_binding(
    lambda message, attrs: "negative" in str(message.get("content", "")).lower(), 
    e2
)
```

::: tip Routing Logic
- When LogicSwitch executes, it evaluates each condition
- Messages are sent to all edges where conditions are true
- Supports multi-path output, one input can be sent to multiple output edges simultaneously
:::

---

### Loop Class {#loop-class}

::: info Loop Graph Structure
Loop is a special graph structure that implements loop logic, allowing repeated execution of subgraphs until termination conditions are met.
:::

```python
class Loop(BaseGraph):
    def __init__(self,
                name: str,
                max_iterations: int = 10,
                model: Model | None = None,
                terminate_condition_prompt: str | None = None,
                terminate_condition_function: Callable | None = None,
                pull_keys: dict[str,dict|str] | None = None,
                push_keys: dict[str,dict|str] | None = None,
                attributes: dict[str,object] | None = None,
                initial_messages: dict[str,object] | None = None,
                edges: list[tuple[str,str] | tuple[str,str,dict[str,dict|str]]] | None = None,
                nodes: list[tuple] | None = None,
                build_func: Callable | None = None)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `name` | `str` | - | Name of the loop |
| `max_iterations` | `int` | `10` | Maximum number of loop iterations |
| `model` | `Model \| None` | `None` | LLM adapter for evaluating termination conditions |
| `terminate_condition_prompt` | `str \| None` | `None` | Prompt for LLM to evaluate termination conditions |
| `terminate_condition_function` | `Callable \| None` | `None` | Termination predicate (takes precedence over `terminate_condition_prompt`) |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | Node variable keys and descriptions extracted from outer layer |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | Node variable keys and descriptions written back after execution |
| `attributes` | `dict[str,object] \| None` | `None` | Initial attributes of the loop graph |
| `initial_messages` | `dict[str,object] \| None` | `None` | Initial messages injected into the internal control flow |
| `edges` | `list[tuple] \| None` | `None` | Declarative edge list `(sender, receiver[, keys])` |
| `nodes` | `list[tuple] \| None` | `None` | Declarative node list (e.g. `(name, NodeTemplate)` or higher-order structures) |
| `build_func` | `Callable \| None` | `None` | Optional build callback (signature: `(graph: BaseGraph) -> None`) |

#### Internal Structure

Loop contains special control nodes internally:

- **Controller**: Controls maximum loop count and evaluates termination conditions at the beginning of each loop
- **TerminateNode**: Used to exit the loop during execution (equivalent to break statement)

#### Special Methods

##### edge_from_controller() {#loop-edge-from}

```python
def edge_from_controller(self, 
                        receiver: Node, 
                        keys: dict[str, dict|str] | None = None) -> Edge
```

Create an edge from the internal Controller to a specified node.

##### edge_to_controller() {#loop-edge-to}

```python
def edge_to_controller(self,
                      sender: Node,
                      keys: dict[str, dict|str] | None = None) -> Edge
```

Create an edge from a specified node to the internal Controller.

##### edge_to_terminate_node() {#loop-edge-terminate}

```python
def edge_to_terminate_node(self,
                          sender: Node,
                          keys: dict[str, dict|str] | None = None) -> Edge
```

Create an edge from a specified node to TerminateNode for early loop exit.

#### Usage Example

```python
# Create loop graph
loop = graph.create_node(Loop,
    name="data_processing_loop",
    max_iterations=5,
    model=model,
    terminate_condition_prompt="Check if expected results have been achieved"
)

# Create processing node within loop
processor = loop.create_node(Agent,
    name="processor",
    model=model,
    instructions="Process data and check if continuation is needed"
)

# Establish loop connections
loop.edge_from_controller(processor, {"data": "Data to process"})
loop.edge_to_controller(processor, {"result": "Processing result"})
```

::: warning Loop Connection Rules
1. Nodes within Loop must connect to internal controller through `edge_from_controller` and `edge_to_controller`
2. Nodes not connected to controller will not participate in loop execution
3. `edge_to_terminate_node` is optional, used for early loop exit
4. Loop ends when maximum iterations are reached or termination conditions are met
:::

---

### Graph Class

::: info Standard Graph Implementation
Graph is the standard implementation of base graph, providing entry and exit nodes, supporting construction of complex node networks.
:::

```python
class Graph(BaseGraph):
    def __init__(self, name: str, 
                pull_keys: dict[str,dict|str] | None = None, 
                push_keys: dict[str,dict|str] | None = None,
                attributes: dict[str,object] | None = None,
                edges: list[tuple[str,str] | tuple[str,str,dict[str,dict|str]]] | None = None,
                nodes: list[tuple] | None = None,
                build_func: Callable | None = None)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `name` | `str` | - | Name of the graph, used for log identification |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | Key-value description mapping for node variables |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | Key-value pairs for updating node variables |
| `attributes` | `dict[str,object] \| None` | `None` | Default node variables |
| `edges` | `list[tuple] \| None` | `None` | Declarative edge list `(sender, receiver[, keys])` |
| `nodes` | `list[tuple] \| None` | `None` | Declarative node list (e.g. `(name, NodeTemplate)` or higher-order structures) |
| `build_func` | `Callable \| None` | `None` | Optional build callback (signature: `(graph: BaseGraph) -> None`) |

#### Core Methods

**edge_from_entry(receiver, keys)**

Create an edge from entry node to specified node.

**edge_to_exit(sender, keys)**

Create an edge from specified node to exit node.

#### Features

- **Entry/Exit Nodes**: Automatically creates EntryNode and ExitNode
- **Polling Execution**: Executes through polling ready nodes until exit is ready
- **Flexible Connections**: Supports arbitrarily complex node connection patterns

---

::: warning Removed Component
`AutoGraph` has been removed from current MASFactory versions.
:::

---

### RootGraph Class

::: info Root Graph Implementation
RootGraph is the outermost graph that can be directly instantiated and invoked by users.
:::

```python
class RootGraph(Graph):
    def __init__(self,
                name: str,
                attributes: dict[str,object] | None = None,
                edges: list[tuple[str,str] | tuple[str,str,dict[str,dict|str]]] | None = None,
                nodes: list[tuple[str, NodeTemplate]] | None = None)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `name` | `str` | - | Name of the graph |
| `attributes` | `dict[str,object] \| None` | `None` | Initial node variables of the graph |
| `edges` | `list[tuple] \| None` | `None` | Declarative edge list `(sender, receiver[, keys])` |
| `nodes` | `list[tuple[str, NodeTemplate]] \| None` | `None` | Declarative node list `[(name, NodeTemplate), ...]` |

#### Core Methods

**invoke(input, attributes=None)**

Start executing RootGraph.

- `input` (dict): System input, needs to align with incoming edge keys
- `attributes` (dict | None): Runtime attributes merged into graph attributes before execution
- Returns: tuple[dict, dict] - `(output_dict, attributes_dict)`

#### Usage Example

```python
graph = RootGraph("demo")
# ... create nodes/edges ...
graph.build()
out, attrs = graph.invoke({"question": "hi"})
```

---

### SingleAgent Class

::: info Single Agent
SingleAgent is a simplified, independent Agent for executing single tasks, can be used independently of Graph.
:::

```python
class SingleAgent(Agent):
    def __init__(self,
                name: str,
                model: Model,
                instructions: str | list[str],
                prompt_template: str | list[str] | None = None,
                max_retries: int = 3,
                retry_delay: int = 1,
                retry_backoff: int = 2,
                tools: list[Callable] = None,
                memories: list[Memory] | None = None,
                retrievers: list[Retrieval] | None = None,
                model_settings: dict | None = None,
                role_name: str = None,
                formatters: list[MessageFormatter] | MessageFormatter | None = None,
                skills: list[Skill] | None = None,
                attributes: dict[str, object] | None = None,
                hide_unused_fields: bool = False,
                reuse_attachment_tags: bool = True)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `name` | `str` | - | Node name |
| `model` | `Model` | - | Model adapter |
| `instructions` | `str \| list[str]` | - | Agent instructions (system prompt) |
| `prompt_template` | `str \| list[str] \| None` | `None` | Prompt template (user prompt) |
| `max_retries` | `int` | `3` | Maximum retries for model calls |
| `retry_delay` | `int` | `1` | Base delay multiplier for exponential backoff retries |
| `retry_backoff` | `int` | `2` | Exponential backoff base |
| `tools` | `list[Callable]` | `None` | Available tools list |
| `memories` | `list[Memory] \| None` | `None` | Memory modules list; at most one `HistoryProvider`-backed memory may be attached |
| `retrievers` | `list[Retrieval] \| None` | `None` | Retrieval adapters (RAG/MCP, etc.) |
| `model_settings` | `dict \| None` | `None` | Model invocation parameters |
| `role_name` | `str \| None` | `None` | Role name |
| `formatters` | `list[MessageFormatter] \| MessageFormatter \| None` | `None` | Optional input/output message formatter(s) |
| `skills` | `list[Skill] \| None` | `None` | Optional loaded skill packages |
| `attributes` | `dict[str, object] \| None` | `None` | Optional default local attributes |
| `hide_unused_fields` | `bool` | `False` | Omit unused template fields from the user payload |
| `reuse_attachment_tags` | `bool` | `True` | Deduplicate same-turn media; if rich history media blocks are available, matching attachments may reuse those existing tags |

#### Features

- **Independent Use**: Can be used independently of graph structure
- **Simplified Interface**: Provides simpler `invoke` method
- **Complete Functionality**: Supports full functionality including tool calls, memory management

---

### DynamicAgent Class

::: info Dynamic Agent
DynamicAgent can dynamically adjust instructions based on input, supporting runtime behavior configuration.
:::

```python
class DynamicAgent(Agent):
    def __init__(self,
                name: str,
                model: Model,
                default_instructions: str = "",
                tools: list[Callable] = None,
                formatters: list[MessageFormatter] | MessageFormatter = None,
                max_retries: int = 3,
                retry_delay: int = 1,
                retry_backoff: int = 2,
                pull_keys: dict[str,dict|str] | None = {},
                push_keys: dict[str,dict|str] | None = {},
                instruction_key: str = "instructions",
                role_name: str = None,
                prompt_template: str = None,
                model_settings: dict | None = None,
                memories: list[Memory] = None,
                retrievers: list[Retrieval] = None,
                attributes: dict[str,object] | None = None)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `name` | `str` | - | Node name |
| `model` | `Model` | - | Model adapter |
| `default_instructions` | `str` | `""` | Default instructions used at initialization; runtime behavior is usually overridden by the field referenced by `instruction_key` |
| `instruction_key` | `str` | `"instructions"` | Key name for dynamic instructions |
| `formatters` | `MessageFormatter \| list[MessageFormatter] \| None` | `None` | Input/output formatters (same semantics as Agent) |
| `max_retries` | `int` | `3` | Maximum retries for model calls |
| `retry_delay` | `int` | `1` | Base delay multiplier for exponential backoff retries |
| `retry_backoff` | `int` | `2` | Exponential backoff base |
| `pull_keys` | `dict[str,dict|str] \| None` | `{}` | Visible/required node attribute keys |
| `push_keys` | `dict[str,dict|str] \| None` | `{}` | Attribute keys written back after execution |
| `memories` | `list[Memory] \| None` | `None` | Memory adapters |
| `retrievers` | `list[Retrieval] \| None` | `None` | Retrieval adapters (RAG/MCP, etc.) |
| `attributes` | `dict[str,object] \| None` | `None` | Initial local attributes for the agent |

#### Features

- **Dynamic Instructions**: At runtime, reads the field named by `instruction_key` from the input message and uses it to override the instructions for the current execution
- **Fallback Semantics**: If the field is missing, the agent keeps using `default_instructions`
- **Flexible Configuration**: Supports custom instruction key names
- **Complete Functionality**: Inherits all functionality from Agent

---

## Skills {#skills}

MASFactory Skills are explicit, directory-based packages centered on an Anthropic-style `SKILL.md` file.
They are loaded in user code and attached to `Agent(..., skills=[...])`.

### Skill Class

```python
@dataclass(frozen=True)
class Skill:
    name: str
    description: str | None
    body: str
    skill_dir: Path
    skill_md_path: Path
    frontmatter: dict[str, Any] = field(default_factory=dict)
    examples: list[Path] = field(default_factory=list)
    templates: list[Path] = field(default_factory=list)
    references: list[Path] = field(default_factory=list)
    scripts: list[Path] = field(default_factory=list)
    raw_markdown: str = ""
```

Parsed Anthropic-style skill package used by MASFactory agents.

#### Important Fields

| Field | Type | Description |
|------|------|------|
| `name` | `str` | Skill name. Falls back to the directory name if omitted from frontmatter. |
| `description` | `str \| None` | Optional skill description from frontmatter. |
| `body` | `str` | Main markdown instructions extracted from `SKILL.md`. |
| `skill_dir` | `Path` | Root directory of the skill package. |
| `skill_md_path` | `Path` | Absolute path to the parsed `SKILL.md` file. |
| `frontmatter` | `dict[str, Any]` | Parsed YAML frontmatter mapping. |
| `examples` | `list[Path]` | Supporting files discovered under `examples/`. |
| `templates` | `list[Path]` | Markdown template files discovered in the skill root. |
| `references` | `list[Path]` | Other supporting files discovered in the package. |
| `scripts` | `list[Path]` | Files discovered under `scripts/`. |
| `raw_markdown` | `str` | Original unmodified contents of `SKILL.md`. |

#### Important Properties

| Property | Type | Description |
|------|------|------|
| `source_path` | `str` | Normalized source directory path of the skill package. |

#### Important Methods

| Method | Returns | Description |
|------|------|------|
| `metadata()` | `dict[str, object]` | Stable metadata used by Agent / visualizer integrations. |
| `render_supporting_files(label, paths)` | `str \| None` | Render a bounded number of supporting files for prompt inclusion. |
| `render_section()` | `str` | Render one full skill directive section. |

### SkillSet Class

```python
@dataclass(frozen=True)
class SkillSet:
    skills: list[Skill] = field(default_factory=list)
```

Skill-side composition view consumed by Agents.
It owns skill rendering/metadata composition so `Agent` does not need to read skill files directly.

#### Core Methods

- `render_instructions() -> str`: Render the `[Loaded Skills]` block
- `compose(base_instructions: str) -> str`: Append rendered skills to base instructions
- `media_assets -> list[MediaAsset]`: Return skill-declared static media assets
- `metadata() -> list[dict[str, object]]`: Return stable metadata for loaded skills

### load_skill()

```python
def load_skill(path: str | Path) -> Skill
```

Load one Anthropic-style skill package from a directory.

**Parameters:**
- `path`: Path to a skill directory containing a required `SKILL.md` file

**Returns:**
- `Skill`: Parsed skill object with normalized paths and discovered supporting files

**Exceptions:**
- `SkillNotFoundError`: If the directory does not exist or `SKILL.md` is missing
- `InvalidSkillPackageError`: If the path exists but is not a valid skill package directory
- `SkillParseError`: If `SKILL.md` cannot be read or parsed into a valid skill definition

**Example:**

```python
from masfactory import load_skill

paper_summary = load_skill("./skills/paper-summary")
```

### load_skills()

```python
def load_skills(paths: Iterable[str | Path]) -> list[Skill]
```

Load multiple skill packages in the order they are provided.

**Parameters:**
- `paths`: Iterable of skill directory paths

**Returns:**
- `list[Skill]`: Parsed skills preserving input order

**Exceptions:**
- `SkillNotFoundError`: If any provided directory does not exist or lacks `SKILL.md`
- `InvalidSkillPackageError`: If any provided path is not a valid skill package directory
- `SkillParseError`: If any `SKILL.md` file cannot be parsed

**Notes:**
- `load_skills()` is fail-fast and stops at the first invalid skill package

**Example:**

```python
from masfactory import load_skills

paper_summary, review_writing = load_skills([
    "./skills/paper-summary",
    "./skills/review-writing",
])
```

### Skill Errors

#### SkillError

Base class for public errors raised by MASFactory Skills APIs.

#### SkillNotFoundError

Raised when the target skill directory does not exist or when the required `SKILL.md` file is missing.

#### InvalidSkillPackageError

Raised when the target path exists but does not conform to the expected skill package layout.

#### SkillParseError

Raised when `SKILL.md` exists but cannot be parsed into a valid skill definition.

---

### AgentSwitch Class

::: info Agent Router
AgentSwitch is an LLM-based switch node: bind each out edge with a natural-language condition; the model evaluates the input and routes to matched edges.
:::

```python
class AgentSwitch(BaseSwitch[str]):
    def __init__(self,
                name: str,
                model: Model,
                pull_keys: dict[str,dict|str] | None = None,
                push_keys: dict[str,dict|str] | None = None,
                attributes: dict[str,object] | None = None,
                routes: dict[str,str] | None = None)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `name` | `str` | - | Agent name |
| `model` | `Model` | - | LLM adapter for evaluating conditions |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | Attribute keys pulled from the outer scope |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | Attribute keys pushed back to the outer scope |
| `attributes` | `dict[str,object] \| None` | `None` | Initial local attributes for this node |
| `routes` | `dict[str,str] \| None` | `None` | Optional declarative routes: `{receiver_node_name: condition_text}` (compiled during `build()`) |

#### Core Methods

**condition_binding(condition, edge)**

Bind condition description for output edge.

- `condition` (str): Condition description text
- `edge` (Edge): Output edge to bind

#### Usage Example

```python
sw = AgentSwitch("router", model)
e1 = graph.create_edge(sw, agent1, {"x": "Solution A"})
e2 = graph.create_edge(sw, agent2, {"x": "Solution B"})
sw.condition_binding("Answer contains keyword yes", e1)
sw.condition_binding("Answer contains keyword no", e2)
```

---

### CustomNode Class

::: info Custom Node
CustomNode allows users to implement custom computation logic through callback functions, an important way to extend MASFactory functionality.
:::

```python
class CustomNode(Node):
    def __init__(self,
                name: str,
                forward: Callable[..., dict[str,object]] | None = None,
                memories: list[Memory] | None = None,
                tools: list[Callable] | None = None,
                retrievers: list[Retrieval] | None = None,
                pull_keys: dict[str,dict|str] | None = None,
                push_keys: dict[str,dict|str] | None = None,
                attributes: dict[str,object] | None = None)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `name` | `str` | - | Name of the node |
| `forward` | `Callable \| None` | `None` | Custom forward function |
| `memories` | `list[Memory] \| None` | `None` | Available memory for current node |
| `tools` | `list[Callable] \| None` | `None` | Available tools for current node |
| `retrievers` | `list[Retrieval] \| None` | `None` | Retrieval adapters available to this node |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | Node variable keys and descriptions extracted from outer layer |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | Key-value descriptions updated to node variables |
| `attributes` | `dict[str,object] \| None` | `None` | Initial local attributes for this node |

#### Forward Callback Function

The core of CustomNode is the forward callback function that defines the node's computation logic. The callback function supports multiple parameter combinations:

```python
# 1 parameter: input data only
def simple_forward(input_data):
    return {"result": f"Processed: {input_data}"}

# 2 parameters: input data + node variables
def forward_with_attributes(input_data, attributes):
    count = attributes.get("count", 0) + 1
    attributes["count"] = count
    return {"result": f"Processing #{count}: {input_data}"}

# 3 parameters: input data + node variables + memory
def forward_with_memory(input_data, attributes, memories):
    if memories:
        memories[0].insert("last_input", str(input_data))
    return {"result": f"Processed with memory: {input_data}"}

# 4 parameters: input data + node variables + memory + tools
def forward_with_tools(input_data, attributes, memories, tools):
    # Can call tools
    return {"result": f"Processed with tools: {input_data}"}

# 5 parameters: input data + node variables + memory + tools + retrievers
def forward_with_retrievers(input_data, attributes, memories, tools, retrievers):
    return {"result": f"Processed with retrievers: {input_data}"}

# 6 parameters: input data + node variables + memory + tools + retrievers + node object
def forward_full(input_data, attributes, memories, tools, retrievers, node):
    return {"result": f"Node {node.name} processed: {input_data}"}
```

#### Core Methods

##### set_forward()

```python
def set_forward(self, forward_callback: Callable) -> None
```

Dynamically set custom forward function.

**Parameters:**
- `forward_callback`: Callback function with same parameter structure as forward in constructor

#### Usage Example

```python
def custom_processor(input_data, attributes, memories, tools, retrievers, node):
    """
    Custom processing function example
    """
    # Implement custom logic
    result = perform_custom_logic(input_data)
    
    # Can access and modify node variables
    attributes["processing_count"] = attributes.get("processing_count", 0) + 1
    
    # Can use memory and tools
    if memories:
        memories[0].insert("last_input", str(input_data))
    
    return {"result": result}

# Create custom node
custom_node = graph.create_node(CustomNode,
    name="custom_processor",
    forward=custom_processor,
    memories=[history_memory],
    tools=[search_tool]
)

# Or dynamically set callback
custom_node = graph.create_node(CustomNode, name="dynamic_node")
custom_node.set_forward(custom_processor)
```

::: warning Callback Function Parameters
- If no forward function is provided, the node will pass input directly to output
- The number of parameters in the callback function determines the number of parameters passed to the function
- Supports callback functions with 1-6 parameters
:::

---

## Model

### Model Class

::: info Model Adapter Base Class
Model is the abstract base class for unified interface to interact with various large language models.
:::

```python
class Model(ABC):
    def __init__(self,
                model_name: str | None = None,
                invoke_settings: dict | None = None,
                *args, **kwargs)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `model_name` | `str \| None` | `None` | Model name |
| `invoke_settings` | `dict \| None` | `None` | Default invocation settings |

#### Important Properties

| Property | Type | Description |
|------|------|------|
| `model_name` | `str` | Name of the model (read-only) |
| `description` | `object` | Description payload of the model (read-only) |

#### Core Methods

##### invoke() *[Abstract Method]*

```python
@abstractmethod
def invoke(self,
          messages: list[dict],
          tools: list[dict] | None,
          settings: dict | None = None,
          **kwargs) -> dict
```

Invoke large language model and get response.

**Parameters:**
- `messages`: List containing conversation history
- `tools`: Optional tools list
- `settings`: Model-specific parameters
- `**kwargs`: Other parameters

**Returns:**
- `dict`: Dictionary containing response type and content

**Return Format:**
```python
# Content response
{"type": ModelResponseType.CONTENT, "content": "..."}

# Tool call response
{"type": ModelResponseType.TOOL_CALL, "content": [
    {"id": str|None, "name": str, "arguments": dict}, ...
]}
```

---

### OpenAIModel Class

::: info OpenAI Responses Model Adapter
`OpenAIModel` uses the OpenAI Responses API and supports multimodal inputs including PDF.
:::

```python
class OpenAIModel(Model):
    def __init__(self,
                model_name: str,
                api_key: str,
                base_url: str | None = None,
                invoke_settings: dict | None = None,
                **kwargs)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `model_name` | `str` | - | OpenAI model name (e.g., "gpt-4o-mini") |
| `api_key` | `str` | - | OpenAI API key |
| `base_url` | `str \| None` | `None` | API base URL |
| `invoke_settings` | `dict \| None` | `None` | Default invocation settings |

#### Common usage

It is common to read credentials/model name from environment variables and pass them explicitly:

```python
import os
from masfactory import OpenAIModel

model = OpenAIModel(
    model_name=os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL") or None,
)
```

#### Supported Settings Parameters

| Parameter | Type | Range | Description |
|------|------|------|------|
| `temperature` | `float` | [0.0, 2.0] | Control output randomness |
| `max_tokens` | `int` | - | Maximum token count |
| `top_p` | `float` | [0.0, 1.0] | Nucleus sampling parameter |
| `stop` | `list[str]` | - | Stop token list |

---

### LegacyOpenAIModel Class

::: info OpenAI Chat Completions Model Adapter
`LegacyOpenAIModel` uses the Chat Completions API for OpenAI-compatible endpoints and does not support PDF input.
:::

```python
class LegacyOpenAIModel(Model):
    def __init__(self,
                model_name: str,
                api_key: str,
                base_url: str | None = None,
                invoke_settings: dict | None = None,
                **kwargs)
```

---

### AnthropicModel Class

::: info Anthropic Model Adapter
AnthropicModel implements the model adapter for interacting with Anthropic Claude API.
:::

```python
class AnthropicModel(Model):
    def __init__(self,
                model_name: str,
                api_key: str,
                base_url: str | None = None,
                invoke_settings: dict | None = None,
                **kwargs)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `model_name` | `str` | - | Anthropic model name (e.g., "claude-3-opus-20240229") |
| `api_key` | `str` | - | Anthropic API key |
| `base_url` | `str \| None` | `None` | API base URL (optional) |
| `invoke_settings` | `dict \| None` | `None` | Default invocation settings |

#### Supported Models

- `claude-3-opus-20240229`
- `claude-3-sonnet-20240229`
- `claude-3-haiku-20240307`

> These examples are illustrative, not an exhaustive or current provider catalog.

---

### GeminiModel Class

::: info Google Gemini Model Adapter
GeminiModel implements the model adapter for interacting with Google Gemini via the `google-genai` SDK.
:::

```python
class GeminiModel(Model):
    def __init__(self,
                model_name: str,
                api_key: str,
                base_url: str | None = None,
                invoke_settings: dict | None = None,
                **kwargs)
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `model_name` | `str` | - | Gemini model name (e.g., "gemini-pro") |
| `api_key` | `str` | - | Google AI API key |
| `base_url` | `str \| None` | `None` | API base URL (optional) |
| `invoke_settings` | `dict \| None` | `None` | Default invocation settings |

#### Supported Models

- `gemini-pro`
- `gemini-pro-vision`
- `gemini-1.5-pro`

> These examples are illustrative, not an exhaustive or current provider catalog.

---

## Memory System

### Memory Class (ContextBlock injection)

::: info Memory = a writable context source
In the current MASFactory API, memories do not expose the legacy `query(...) -> str` interface.  
Instead, a Memory acts as a context source (ContextProvider) and returns structured `ContextBlock`s
via `get_blocks(...)`, which Agents inject into the user payload as a `CONTEXT` field during Observe.
:::

```python
class Memory(ContextProvider, ABC):
    def __init__(self, context_label: str, *, passive: bool = True, active: bool = False)
    def insert(self, key: str, value: object)
    def update(self, key: str, value: object)
    def delete(self, key: str, index: int = -1)
    def reset(self)
    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]
```

#### Key semantics

- `context_label`: source label (used in rendering and debugging)
- `passive=True`: auto-inject into `CONTEXT`
- `active=True`: exposed as tools for on-demand retrieval (`retrieve_context`)

For details, see: [`/guide/context_adapters`](/guide/context_adapters).

---

### HistoryMemory Class (chat history)

::: info HistoryMemory
`HistoryMemory` stores chat history and injects it as chat-style `messages` (between system and user).  
It does not emit `ContextBlock`s (`get_blocks(...)` always returns empty).
An `Agent` may attach at most one `HistoryProvider`-backed memory. It may optionally merge duplicate historical media when returning `get_messages(...)`; this behavior is controlled by `merge_historical_media` on the memory itself. When enabled, repeated attachments are returned as indexed tag references instead of duplicate media blocks.
:::

```python
class HistoryMemory(Memory, HistoryProvider):
    def __init__(
        self,
        top_k: int = 10,
        memory_size: int = 1000,
        context_label: str = "CONVERSATION_HISTORY",
        *,
        merge_historical_media: bool = True,
    )
    def insert(self, role: str, response: object)
    def get_messages(self, query: ContextQuery | None = None, *, top_k: int = -1) -> list[dict]
```

#### top_k convention

- `top_k=-1`: use the instance default configured in `__init__`
- `top_k=0`: return as many as possible (bounded by `memory_size`)
- `top_k<0`: return empty

#### Example

```python
from masfactory import HistoryMemory

memory = HistoryMemory(top_k=10, memory_size=50)
memory.insert("user", "Hello, tell me about MASFactory")
memory.insert("assistant", "Sure.")

print(memory.get_messages(top_k=2))
```

> When `HistoryMemory` is attached via `Agent(memories=[...])`, Agent automatically inserts the
> returned `get_messages(...)` items into `messages` between system and user.

---

### VectorMemory Class (semantic memory)

::: info VectorMemory
`VectorMemory` ranks stored items by embedding cosine similarity and injects them into `CONTEXT`
as `ContextBlock`s.
:::

```python
class VectorMemory(Memory):
    def __init__(
        self,
        embedding_function: Callable[[str], np.ndarray],
        top_k: int = 10,
        query_threshold: float = 0.8,
        memory_size: int = 20,
        context_label: str = "SEMANTIC_KNOWLEDGE",
        *,
        passive: bool = True,
        active: bool = False,
    )
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `embedding_function` | `Callable[[str], np.ndarray]` | - | Function that maps text to an embedding vector |
| `top_k` | `int` | `10` | Default number of blocks to return when injecting context |
| `query_threshold` | `float` | `0.8` | Similarity threshold |
| `memory_size` | `int` | `20` | Max number of stored items |
| `context_label` | `str` | `"SEMANTIC_KNOWLEDGE"` | Context source label |

#### Notes

- `get_blocks(...)` uses `ContextQuery.query_text` as the retrieval query (best-effort extracted by Agents).
- Returned blocks include a similarity `score` for debugging.

::: warning Legacy note
If you see older docs mentioning `KeyValueMemory / SummaryMemory / StorageVectorMemory`: those types are
not part of the current API surface.
:::

---

## Enumeration Types

### ModelResponseType

::: info Model Response Type
Defines enumeration for large language model response types.
:::

```python
class ModelResponseType(Enum):
    CONTENT = "content"      # Plain text content
    TOOL_CALL = "tool_call"  # Tool call request
```

#### Enumeration Values

| Value | Literal | Description |
|----|----|------|
| `TOOL_CALL` | `"tool_call"` | Indicates model's response is one or more tool call requests |
| `CONTENT` | `"content"` | Indicates model's response is plain text content |

### Gate

::: info Gate State
Defines open/closed state for nodes and edges.
:::

```python
class Gate(Enum):
    CLOSED = "CLOSED"  # Closed state
    OPEN = "OPEN"      # Open state
```

## Tool System

### ToolAdapter Class

::: info Tool Adapter
ToolAdapter manages a set of callable tool functions and can convert them to JSON Schema format required by LLM.
:::

```python
class ToolAdapter:
    def __init__(self, tools: list[Callable])
```

#### Constructor Parameters

| Parameter | Type | Description |
|------|------|------|
| `tools` | `list[Callable]` | List of callable functions managed as tools |

#### Important Properties

##### details

```python
@property
def details(self) -> dict
```

Generate detailed information for all registered tools in JSON Schema format.

**Returns:**
- `dict`: List containing descriptions of all tools, each description includes "name", "description", and "parameters"

**Features:**
- Automatic introspection of function signatures and docstrings
- Supports type mapping for Optional/Union/List/Dict etc.
- Builds descriptions compliant with LLM function call specifications

#### Core Methods

##### call()

```python
def call(self, name: str, arguments: dict) -> str
```

Call tool by name and arguments.

**Parameters:**
- `name`: Name of the tool to call (function name)
- `arguments`: Parameter dictionary passed to tool function

**Returns:**
- `str`: Return value after tool function execution

#### Tool Function Specifications

Tool functions need to follow these specifications to ensure correct JSON Schema generation:

```python
def web_search(query: str, max_results: int = 5) -> str:
    """
    Search for information on the web
    
    Args:
        query (str): Search keywords
        max_results (int): Maximum number of results, default is 5
        
    Returns:
        str: Text description of search results
    """
    # Implement search logic
    results = perform_web_search(query, max_results)
    return format_search_results(results)

def calculate_statistics(numbers: list[float]) -> dict:
    """
    Calculate statistical information for a list of numbers
    
    Args:
        numbers (list[float]): List of numbers
        
    Returns:
        dict: Statistical information including mean, max, min values
    """
    import statistics
    return {
        "mean": statistics.mean(numbers),
        "median": statistics.median(numbers),
        "max": max(numbers),
        "min": min(numbers),
        "std_dev": statistics.stdev(numbers)
    }
```

#### Usage Example

```python
# Define tool functions
tools = [web_search, calculate_statistics]

# Create tool adapter
tool_adapter = ToolAdapter(tools)

# Get tool details (JSON Schema format)
tool_details = tool_adapter.details

# Manually call tool
result = tool_adapter.call("web_search", {
    "query": "artificial intelligence", 
    "max_results": 3
})

# Use tools in Agent
agent = graph.create_node(Agent,
    name="tool_agent",
    model=model,
    instructions="You are an assistant with multiple tool capabilities",
    tools=tools
)
```

#### Supported Type Mapping

| Python Type | JSON Schema Type |
|-------------|------------------|
| `str` | `{"type": "string"}` |
| `int` | `{"type": "integer"}` |
| `float` | `{"type": "number"}` |
| `bool` | `{"type": "boolean"}` |
| `list[T]` | `{"type": "array", "items": <T mapping>}` |
| `dict` | `{"type": "object"}` |
| `Optional[T]` | Union type handling |
| `Union[T1, T2, ...]` | `{"anyOf": [<T1 mapping>, <T2 mapping>, ...]}` |

::: tip Tool Function Best Practices
1. **Complete Type Annotations**: Ensure all parameters and return values have type annotations
2. **Detailed Docstrings**: Provide clear function descriptions and parameter explanations
3. **Error Handling**: Add appropriate error handling in tool functions
4. **Consistent Return Format**: Maintain consistency in tool function return formats
:::

## Retrieval Module (RAG / Retrieval)

### Retrieval Class (ContextBlock injection)

::: info Retrieval = a read-only context source
In the current MASFactory API, retrievers (RAG) return structured `ContextBlock`s via `get_blocks(...)`.
Agents inject selected blocks into the user payload as a `CONTEXT` field during Observe.
:::

```python
class Retrieval(ContextProvider, ABC):
    def __init__(self, context_label: str, *, passive: bool = True, active: bool = False)
    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]
```

#### top_k convention (built-ins)

- `top_k=0`: return as many as possible
- `top_k<0`: return empty

For more on passive vs active retrieval (tools), see: [`/guide/context_adapters`](/guide/context_adapters).

---

### VectorRetriever Class

::: info Vector Retrieval Implementation
VectorRetriever retrieves relevant documents based on vector embeddings and similarity search.
:::

```python
class VectorRetriever(Retrieval):
    def __init__(
        self,
        documents: dict[str, str],
        embedding_function: Callable[[str], np.ndarray],
        *,
        similarity_threshold: float = 0.7,
        context_label: str = "VECTOR_RETRIEVER",
        passive: bool = True,
        active: bool = False,
    )
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `documents` | `dict[str, str]` | - | Mapping from document ID to document content |
| `embedding_function` | `Callable[[str], np.ndarray]` | - | Text → embedding function |
| `similarity_threshold` | `float` | `0.7` | Similarity threshold |
| `context_label` | `str` | `"VECTOR_RETRIEVER"` | Context source label |

#### Features

- **Vector Embeddings**: Pre-compute vector embeddings for all documents
- **Cosine Similarity**: Use cosine similarity to calculate relevance between query and documents
- **Efficient Retrieval**: Fast retrieval based on vector similarity

---

### FileSystemRetriever Class

::: info File System Retrieval Implementation
FileSystemRetriever loads documents from file system and supports vector retrieval with caching capabilities.
:::

```python
class FileSystemRetriever(Retrieval):
    def __init__(
        self,
        docs_dir: str | Path,
        embedding_function: Callable[[str], np.ndarray],
        *,
        file_extension: str = ".txt",
        similarity_threshold: float = 0.7,
        cache_path: str | Path | None = None,
        context_label: str = "FILESYSTEM_RETRIEVER",
        passive: bool = True,
        active: bool = False,
    )
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `docs_dir` | `str` | - | Document directory path |
| `embedding_function` | `Callable[[str], np.ndarray]` | - | Text → embedding function |
| `file_extension` | `str` | `".txt"` | File extension to load |
| `similarity_threshold` | `float` | `0.7` | Similarity threshold |
| `cache_path` | `str \| Path \| None` | `None` | Embedding cache file path |
| `context_label` | `str` | `"FILESYSTEM_RETRIEVER"` | Context source label |

#### Features

- **File System Scanning**: Automatically scan document files in specified directory
- **Caching Mechanism**: Support persistent caching of embedding vectors
- **Flexible Configuration**: Support various file extensions and directory structures

---

### SimpleKeywordRetriever Class

::: Info Keyword Retrieval Implementation
SimpleKeywordRetriever uses keyword matching for document retrieval, suitable for simple scenarios.
:::

```python
class SimpleKeywordRetriever(Retrieval):
    def __init__(
        self,
        documents: dict[str, str],
        *,
        context_label: str = "KEYWORD_RETRIEVER",
        passive: bool = True,
        active: bool = False,
    )
```

#### Constructor Parameters

| Parameter | Type | Default | Description |
|------|------|--------|------|
| `documents` | `dict[str, str]` | - | Mapping from document ID to document content |
| `context_label` | `str` | `"KEYWORD_RETRIEVER"` | Context source label |

#### Features

- **Keyword Matching**: Calculate relevance based on simple word frequency statistics
- **Lightweight Implementation**: No need for vector embeddings, low computational overhead
- **Quick Deployment**: Suitable for small document sets or prototype development

---

## MCP (external context sources)

### MCP Class

::: info MCP = integrate external context via a callable
`MCP` is a lightweight ContextProvider. You provide a callable that returns items, and MASFactory maps
them into `ContextBlock`s and injects them into `CONTEXT`.
:::

```python
class MCP(ContextProvider):
    def __init__(
        self,
        *,
        name: str = "MCP",
        call: Callable[[ContextQuery, int], Iterable[dict[str, Any]]],
        text_key: str = "text",
        uri_key: str = "uri",
        chunk_id_key: str = "chunk_id",
        score_key: str = "score",
        title_key: str = "title",
        metadata_key: str = "metadata",
        dedupe_key_key: str = "dedupe_key",
        passive: bool = True,
        active: bool = False,
    )
```

#### Example (Observe-only injection)

```python
from masfactory import Agent
from masfactory.adapters.context.types import ContextQuery
from masfactory.adapters.mcp import MCP

def call(query: ContextQuery, top_k: int):
    return [{"text": f"[MCP] {query.query_text}", "uri": "mcp://demo"}]

mcp_provider = MCP(name="DemoMCP", call=call, passive=True, active=False)

agent = Agent(
    name="demo",
    model=object(),
    instructions="You are a concise assistant.",
    prompt_template="{query}",
    retrievers=[mcp_provider],
)

_, user_prompt, _ = agent.observe({"query": "What is MCP?"})
print(user_prompt)
```

## Workflow Compatibility

The compatibility package imports external workflow documents into MASFactory graphs.

::: tip User Guide
For task-oriented examples, see [`Workflow Compatibility`](/guide/compatibility).
:::

### Import Functions

```python
from masfactory.compatibility import (
    load_graph_from_dify_yaml,
    load_graph_from_dify_dict,
    load_graph_from_chatdev_yaml,
    load_graph_from_langflow_json,
)
```

#### load_graph_from_dify_yaml()

```python
def load_graph_from_dify_yaml(
    source: str | Path | bytes,
    *,
    graph_name: str | None = None,
    options: DifyCompileOptions | None = None,
    graph_design_path: str | Path | bool | None = None,
    aml_path: str | Path | bool | None = None,
) -> Graph
```

Loads a Dify YAML export. `kind: app` documents are compiled with Dify runtime semantics; generic `{nodes, edges}` documents are compiled as passthrough graphs.

#### load_graph_from_dify_dict()

```python
def load_graph_from_dify_dict(
    doc: dict,
    *,
    graph_name: str | None = None,
    options: DifyCompileOptions | None = None,
    graph_design_path: str | Path | bool | None = None,
    aml_path: str | Path | bool | None = None,
) -> Graph
```

Loads a Dify mapping that has already been parsed in Python.

#### load_graph_from_chatdev_yaml()

```python
def load_graph_from_chatdev_yaml(
    source: str | Path | bytes,
    *,
    graph_name: str = "chatdev_import",
    options: ChatDevCompileOptions | None = None,
    use_placeholder: bool = False,
    graph_design_path: str | Path | bool | None = None,
    aml_path: str | Path | bool | None = None,
) -> ChatDevRootGraph | Graph
```

Loads a ChatDev workflow YAML or chain-style configuration. Set `use_placeholder=True` to build a topology-only passthrough graph.

#### load_graph_from_langflow_json()

```python
def load_graph_from_langflow_json(
    source: str | Path | bytes,
    *,
    graph_name: str = "langflow_import",
    options: LangflowCompileOptions | None = None,
    graph_design_path: str | Path | bool | None = None,
    aml_path: str | Path | bool | None = None,
) -> LangflowRootGraph
```

Loads a Langflow JSON export and compiles common chat-flow components into executable MASFactory nodes.

### Common Loader Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `source` | `str \| Path \| bytes` | File path, inline document text, or UTF-8 bytes |
| `graph_name` | `str \| None` | Name assigned to the generated graph |
| `options` | Compile options | Product-specific runtime options |
| `aml_path` | `str \| Path \| bool \| None` | Optional AML export path for Visualizer preview and migration review |
| `graph_design_path` | `str \| Path \| bool \| None` | Optional legacy Visualizer `graph_design.json` export path |

`aml_path=True` writes a generated `.aml` file under `masfactory/compatibility/out/`. `graph_design_path=True` writes the legacy JSON preview format. Relative paths are resolved under that directory; absolute paths are used directly.

### Compile Options

#### DifyCompileOptions

```python
@dataclass
class DifyCompileOptions:
    model_factory: Callable[[dict[str, Any]], Model] | None = None
    use_stub_llm: bool = False
    llm_stub_text: str = "stub-llm-response"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    tool_executor: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None
    http_client: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    knowledge_retriever: Callable[[dict[str, Any], str], str] | None = None
```

By default, Dify LLM nodes resolve a real OpenAI-compatible model from Dify model settings. Set `use_stub_llm=True` for offline tests.

#### ChatDevCompileOptions

```python
@dataclass
class ChatDevCompileOptions:
    model_factory: Callable[[dict[str, Any]], Model] | None = None
    use_stub_llm: bool = True
    llm_stub_text: str = "stub-chatdev-response"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
```

#### LangflowCompileOptions

```python
@dataclass
class LangflowCompileOptions:
    model_factory: Callable[[dict[str, Any]], Model] | None = None
    use_stub_llm: bool = True
    llm_stub_text: str = "stub-langflow-response"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
```

### AML Helpers

```python
from masfactory.compatibility import (
    dify_document_to_aml,
    chatdev_document_to_aml,
    langflow_document_to_aml,
    blueprint_to_aml_document,
    export_aml_for_blueprint,
    write_aml,
)
```

These helpers produce AML documents for Visualizer preview, source-level inspection, and migration workflows.

### Legacy Graph Design Helpers

```python
from masfactory.compatibility import (
    dify_document_to_graph_design,
    chatdev_document_to_graph_design,
    langflow_document_to_graph_design,
    write_graph_design_json,
)
```

These helpers produce Visualizer-previewable `{"graph_design": ...}` documents without building an executable graph. They remain available for legacy preview tooling; prefer AML helpers for new workflows.

### Blueprint-Level APIs

The lower-level blueprint APIs are intended for extension work:

```python
from masfactory.compatibility import (
    blueprint_to_graph,
    blueprint_to_dify_graph,
    blueprint_to_chatdev_graph,
    blueprint_to_langflow_graph,
    blueprint_to_aml_document,
    workflow_export_to_blueprint,
)
```

`GraphBlueprint` is the normalized intermediate representation used by the importers. It contains `ExternalNode` and `ExternalEdge` records before they are materialized into MASFactory nodes and edges.
