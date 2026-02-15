# 基础组件
组件是 MASFactory 中构成工作流的元素。这些组件包括 `Node` 类组件、`Edge` 组件和 `Message` 组件。
- `Node`：`Graph` 上的抽象计算单元，其中 Graph、Agent、控制逻辑等均为 `Node` 的派生类
- `Edge`：连接两个节点，用于流程控制与消息自动转发。
- `Message`：提供统一的消息解析与分发机制。`Message` 由 MASFactory 自动处理，开发者只需告知 MASFactory 使用哪一种 `MessageFormatter` 来处理节点消息。

::: tip Node 组件
`Node` 组件不直接出现在 MASFactory 的工作流（Workflow）中，而是以其派生类的形式出现，如 `Graph`、`Agent`、`Switch` 等。它们承担着子工作流、计算与控制等核心功能。下面介绍的所有组件均为 `Node` 类组件。
:::

## 顶层组件：

顶层组件指可由用户直接实例化并独立运行的对象。它们是最外层的节点，既不隶属于任何 `Graph`，也不会作为其他 `Graph` 的 `Node` 或子图。
MASFactory 提供两类顶层组件：`SingleAgent` 与 `RootGraph`。

### `RootGraph`
顶层可执行的工作流容器。可被用户直接实例化，作为“画布”承载节点与边，组织整体 DAG，并负责一次性执行与结果产出。主要方法：
- 构造参数： `name`、`attributes`? <br>
  其中 `name` 为 RootGraph 的名称；`attributes` 为 RootGraph 的节点变量，所有子图和节点均可访问。
::: tip 节点变量
有关`节点变量`的详细介绍请参考：[概念-节点变量](/zh/guide/concepts#节点变量)
:::
- 相关方法：
    ::: tip 方法说明
    `RootGraph` 派生自 `Graph`，因此下面的方法 `create_node`、`create_edge`、`edge_from_entry` 和 `edge_to_exit` 实际上继承自 `Graph`。<br>
    同时，`RootGraph` 和 `Graph` 均是 `Node` 的子类，其中 `build` 方法在 `Node` 中声明，并在其所有子类中均有不同的实现。
    :::
    - `create_node`：参数包括 `cls`、`*args`、`**kwargs`；返回 `Node`。<br>
  在 `RootGraph` 上创建一个节点（如 `Agent`、`DynamicAgent`、`AgentSwitch`、`LogicSwitch`、`Graph`、`Loop`、`CustomNode` 等）。其中 `cls` 必须为 `Node` 子类（禁止 `SingleAgent` 与 `RootGraph` 作为图内节点）。其余参数原样传递给对应构造函数，返回该节点实例。
    - `create_edge`：参数包括 `sender`、`receiver`、`keys`?；返回 `Edge`。<br>
  在当前图中的两个节点间创建有向边。其中 `keys` 定义需传递的字段及其自然语言描述。内部包含环路与重复边校验；创建成功后自动登记到两端节点与图中。
    - `edge_from_entry`：参数包括 `receiver`、`keys`?；返回 `Edge`。<br>
  创建一个从图入口到图中节点 `receiver` 的有向边。
    - `edge_to_exit`：参数包括 `sender`、`keys`?；返回 `Edge`。<br>
  创建一个从图中节点 `sender` 到图出口的有向边。
    - `build`：无参数。<br>
  递归构建 `RootGraph` 及其子图和节点，并完成一致性检查。在调用 `invoke` 前必须执行此方法。
    - `invoke`：参数包括 `input`、`attributes`?；返回 `(dict, dict)`。<br>
  启动工作流执行。其中 `input` 的格式需与入口边 `keys` 对齐；返回 `(output_dict, attributes_dict)`。
::: warning Graph 约束（实践建议）
为避免执行期死锁/提前退出，建议遵守以下约束：<br>
1. 尽量避免孤立节点（入度为 0 或出度为 0 的节点）；<br>
2. 创建与 `entry` 和 `exit` 相连的边时，必须使用 `edge_from_entry` 或 `edge_to_exit` 接口，不可使用 `create_edge` 接口；<br>
3. `create_edge` 接口中的 `receiver` 和 `sender` 节点必须是使用当前 Graph 的 `create_node` 接口创建的 `Node` 对象；<br>
4. 所有的 `Node` 和 `Edge` 不能出现环路。如果需要使用循环工作流，请使用 `Loop` 组件。
:::
- 示例参考: [创建一个直线工作流](/zh/examples/sequential_workflow)


### `SingleAgent`
单智能体组件。它不依赖于任何 Graph 即可独立使用的 Agent 组件，用户可以直接实例化并使用。<br>
适用于快速问答、简单工具调用、脚本化批处理等无需完整工作流编排的任务。
- 构造参数： `name`、`model`、`instructions`、`prompt_template`?、`tools`?、`memories`?、`model_settings`?、`role_name`? <br>
  参数含义参考 [Agent](#Agent)。
- 相关方法：
    - `invoke`：参数包括 `input`（`dict`）；返回 `dict`。<br>
    `SingleAgent` 的输入/输出都使用 `dict`（由配置的 `MessageFormatter` 解析/生成）。
- 示例：[创建一个单智能体工作流](/zh/examples/agents)

## 子图组件

子图组件不能被用户直接实例化，而是通过其他 `Graph` 实例的 `create_node` 接口创建。得到的子图对象同样拥有 `create_node` 和 `create_edge` 接口，可以拥有自己的内部 `Node`。子图通过母图的 `create_edge` 接口与同层的其他 `Node` 相连接，从而形成 DAG 结构。

### `Graph`
子工作流节点，支持复用与嵌套。
- 构造参数： `name`、`pull_keys`?、`push_keys`?、`attributes`? <br>
    其中 `name` 为图名称，用于日志中的标识；<br>
    `pull_keys`、`push_keys` 和 `attributes` 均为节点变量控制逻辑。`pull_keys` 控制从母图中的节点变量中提取相应字段；`push_keys` 控制向母图中更新相应字段；`attributes` 为本节点自带的节点变量字段。相关介绍参考：[概念-节点变量](/zh/guide/concepts#节点变量)。
- 特点：内置 `Entry`/`Exit`，作为“阶段”承载多个节点；继承 `BaseGraph` 的节点/边管理与一致性校验。
- 相关方法：`edge_from_entry`、`edge_to_exit`、`create_node`和`create_edge`，具体介绍参考: [RootGraph](#RootGraph)。
- 适用场景：将复杂流程划分为若干子阶段，便于复用与调试。

### `Loop`
循环子图，封装迭代控制与可选的 LLM 终止判定功能。
- 构造参数：`name`、`max_iterations`、`model`?、`terminate_condition_prompt`?、`terminate_condition_function`?、`pull_keys`?、`push_keys`?、`attributes`? 
    - `max_iterations`：控制最大循环次数。
    - `model` 和 `terminate_condition_prompt`：用于设定使用 LLM 判定终止条件的模型和逻辑。
    - `terminate_condition_function`：推荐的 Python 终止判定函数（返回 True 表示终止）。
    - `pull_keys`、`push_keys` 和 `attributes`：控制节点变量逻辑，详细参考：[概念-节点变量](/zh/guide/concepts#节点变量)。
- 特点：内部包含一个 `Controller` 节点，在每次循环开始检查 `max_iterations` 条件和 `terminate_condition_prompt` 条件；`TerminateNode` 支持在循环体内提前退出。
- 相关方法：
    - `create_node` 和 `create_edge`：使用方法同：[RootGraph](#RootGraph)。
	- `edge_from_controller`：参数包括 `receiver`、`keys` 等；返回 `Edge`（从控制器启动每轮迭代）。
	- `edge_to_controller`：参数包括 `sender`、`keys` 等；返回 `Edge`（结果回灌控制器形成下一轮输入）。
	- `edge_to_terminate_node`：参数包括 `sender`、`keys` 等；返回 `Edge`（在循环体内触发强制终止）。
- 终止条件：达到 `max_iterations` 或经 LLM 判定满足 `terminate_condition_prompt` 时终止。
- 强制跳出循环：当 `terminate_node` 收到任意消息时立即跳出。
- 示例：[Loop示例](/zh/examples/looping)
::: warning Loop 约束
1. `Loop` 中必须形成以 `Controller` 为核心的循环路径，并且除此环路外，不允许出现其他环路。
2. `Controller` 只在每次迭代开始前做跳出循环判断。如果需要在中途退出循环，请使用 `TerminateNode` 节点退出循环。
3. 连接到 `Controller` 节点和 `TerminateNode` 节点的边必须通过 `edge_from_controller`、`edge_to_controller` 和 `edge_to_terminate_node` 接口创建，不能通过 `create_edge` 接口创建。
4. 当 `TerminateNode` 收到消息后，会立即触发退出机制（相当于编程语言的 `break` 跳出循环的逻辑）。
5. `edge_from_controller`、`edge_to_controller`、`edge_to_terminate_node` 以及 `Loop` 的 `in_edges` 和 `out_edges` 上的 `keys` 必须相同，以避免出错。
:::

## Agent 组件
### `Agent`
标准智能体节点。
- 构造参数：`name`、`model`、`instructions`、`prompt_template`?、`formatters`?、`tools`?、`memories`?、`retrievers`?、`pull_keys`?、`push_keys`?、`model_settings`?、`role_name`?、`hide_unused_fields`?<br>
    - `name`：节点名称，用于标识当前 Agent；<br>
    - `model`：Agent 所调用的大模型，接收一个 `Model` 对象，对主流 LLM API 进行了适配。详细参考：[模型适配器](/zh/guide/model_adapter)；<br>
    - `instructions`：用于发送给 Agent 的指令信息。接收一个字符串或字符串列表；当为列表时将以换行符拼接成完整的指令。支持使用 `{替换字段}` 将 `in_edges` 中的 `keys` 字段、节点变量 `attributes` 中的字段、`role_name` 嵌入到指令中；<br>
    - `prompt_template`：Agent 的 prompt 模板（对应 user prompt）。支持 `str` 或 `list[str]`；当为列表时将以换行符拼接；可与 `instructions` 组合使用；默认为 `None`；<br>
    - `formatters`：消息格式化器（LLM I/O 的“协议”）。可传单个 formatter（同时用于输入/输出），或传 `[in_formatter, out_formatter]` 两个 formatter。默认使用“段落式输入 + JSON 输出”。<br>
    - `tools`：可供 Agent 调用的工具函数列表。函数名、参数名、返回值类型和 docstring 将被 MASFactory 自动添加到 LLM 上下文中，依据 LLM 调用结果自动调用对应工具，并将结果返回给 LLM；<br>
	- `memories`：记忆模块列表（写入 + 读取）。除 `HistoryMemory` 外，其它 Memory 作为上下文源通过 `get_blocks(...)` 注入 `CONTEXT`；同时 Agent 会在每次 step 后调用 `insert(...)` 写入本轮输出。<br>
	- `retrievers`：RAG / 外部上下文源列表（只读）。通过 `get_blocks(...)` 注入 `CONTEXT`。MCP 形态的上下文源也可通过该参数接入。<br>
	- `model_settings`：传递给底层模型接口的附加设置（参考 OpenAI Chat Completions Legacy 接口）。支持：`temperature`（浮点数，范围 [0.0, 2.0]）、`top_p`（浮点数，范围 [0.0, 1.0]）、`max_tokens`（正整数）、`stop`（停止词，`str` 或 `list[str]`）。未列出的键将按原样透传给模型适配器（若模型支持）。例如：`{"temperature": 0.7, "top_p": 0.95, "max_tokens": 512, "stop": ["</end>"]}`；<br>
    - `role_name`：Agent 的角色名称。可使用 `{role_name}` 将其插入到 instructions 中。如果未设置 `role_name`，则 `role_name` 直接使用 `name` 的值。
    - `hide_unused_fields`：当为 `True` 时，未被模板占位符消费的输入字段不会被自动附加到 user prompt（更“干净”的提示，但也更容易漏信息）。
- 特性：
  - 模型适配：适配主流模型 API 接口。
  - 自动工具调用：当 LLM 返回工具调用时自动执行对应工具，回填结果并再次请求 LLM，直到返回最终内容。
  - 记忆与 RAG 注入：Memory / Retrieval / MCP 统一产出 `ContextBlock`，由 Agent 在 Observe 阶段注入到 user prompt 的 `CONTEXT` 字段；支持 passive（自动注入）与 active（按需检索，工具调用）两种模式。
  - 系统指令与用户模板：`instructions` 支持 `str` 或 `list` 与占位符（如 `{role_name}`、入边 `keys`、节点变量）；可以使用 `prompt_template` 对 `in_edges` 的输入进行修饰。
  - 结构化输出约束：基于出边 `output_keys` 自动生成 JSON 字段约束提示，引导模型严格输出。
  - 节点变量支持：遵循 `Node` 的 `pull_keys`、`push_keys` 和 `attributes` 规则；`Agent` 默认 `pull_keys` 和 `push_keys` 为空字典。
  
 - 相关方法：
   - `build()`：将 `Agent` 标记为可执行（通常由 `Graph` 统一调用）。
   - `add_memory(memory: Memory)`：添加记忆适配器（用于 `get_blocks` 注入与 step 后 `insert` 写入）。
   - `add_retriever(retriever: Retrieval)`：添加检索/上下文源（用于 `get_blocks` 注入，或 active 模式按需检索）。
- 示例：[Agent示例](/zh/examples/agents)
::: tip 深入阅读
- Agent 的 Observe/Think/Act：[`/zh/guide/agent_runtime`](/zh/guide/agent_runtime)
- RAG / Memory / MCP 的 ContextBlock 注入：[`/zh/guide/context_adapters`](/zh/guide/context_adapters)
:::


### `DynamicAgent`
动态智能体节点。<br>
`DynamicAgent` 节点与 `Agent` 相似，唯一不同之处在于，`DynamicAgent` 节点的 `instructions` 不是在编码时确定的，而是在运行时从 `in_edges` 的消息中提取的。<br>
`DynamicAgent` 在运行时会从输入消息中读取 `instruction_key`（默认为 `"instructions"`）对应的字段，并用该字段动态覆盖本轮执行的 `instructions`（随后会从输入里移除该字段再执行）。
因此在使用 `DynamicAgent` 时，务必保证上游节点/入边会提供该字段（否则会触发 KeyError）。
- 构造参数： `name`、`model`、`default_instructions`、`instruction_key`?、`prompt_template`?、`tools`?、`memories`?、`retrievers`?、`pull_keys`?、`push_keys`?、`model_settings`?、`role_name`? <br>
  - `default_instructions`：默认指令（初始化时使用）。实际运行时通常由上游通过 `instruction_key` 字段每次动态提供；<br>
  - `instruction_key`：入边消息中用于“动态覆盖指令”的键名，默认值为 `"instructions"`。如果在入边消息中检测到该键，则本轮执行将以其值作为指令并覆盖 `default_instructions`；<br>
  - `name`、`model`、`tools`、`memories`、`pull_keys`、`model_settings`、`model_settings`、`prompt_template`：同 [Agent](#Agent)；<br>
- 使用示例：[DynamicAgent示例](/zh/examples/agents)

## 条件分支组件

分支组件类似于程序设计语言中的 if 分支，基于当前的状态和条件决定下一条路的走向。MASFactory 提供两种分支组件：基于回调函数的逻辑分支组件 `LogicSwitch` 和基于 Agent 语义判断的语义分支组件 `AgentSwitch`。
### `LogicSwitch`
基于回调函数的条件路由组件，使用 `condition_binding`(callback, out_edge) 绑定分支条件。

- 构造参数：`name`、`pull_keys`?、`push_keys`?（含义同 [`Agent`](#Agent)）
- 相关方法：
  - `condition_binding(callback, out_edge)`：将一条 `out_edge` 与条件回调函数绑定。
    - `callback(message, attributes) -> bool`：其中 `message` 为入边聚合后的消息（`dict`），`attributes` 为节点变量 dict；返回 `True` 时向该 `out_edge` 转发消息并将该 `out_edge` 所连接的 `target` 节点放入待执行队列中。
::: tip LogicSwitch 和 AgentSwitch
1. `LogicSwitch` 会将`in_edges`传入的消息`message`、从母图中继承的节点变量`attributes`传入所有out_edges对应的回调函数，并依据回调函数的返回值决定是否将该`out_edges`所连接的目标节点放入待执行队列。
2. `LogicSwitch` 支持“多路匹配”，既如果由多个`out_edge`对应的条件函数返回`True`，则这些路径上的节点都被放入待执行队列。
3. `AgentSwitch` 与`LogicSwitch` 处理逻辑相似。不同之处在于，`LogicSwitch`使用回调函数进行条件判断，而`AgentSwitch`使用LLM基于条件语义进行条件判断。
:::
::: warning 需要避免的情况
1. 如果某个 `out_edge` 没有被绑定条件回调函数或条件语义，则这条边对应的目标节点将永远不会被加入到执行队列中。开发中应当避免这种情况。
2. 如果某次执行中所有 `out_edge` 对应的条件都返回 `False`，Switch 会关闭所有出边且不会转发消息；当执行队列为空时，工作流会提前结束。为避免“无匹配”带来的意外，建议增加**默认/兜底分支**（例如一个永远返回 `True` 的条件），或显式处理“无分支命中”的情况。
:::
- 使用示例：[逻辑分支示例](/zh/examples/conditional_branching)


### `AgentSwitch`
基于 LLM 的语义路由组件，使用 `condition_binding`(prompt, out_edge) 绑定路由语义。

- 构造参数：`name`、`model`、`pull_keys`?、`push_keys`?（含义同 [`Agent`](#Agent)）
- 相关方法：
  - `condition_binding(prompt, out_edge)`：为某条出边绑定语义判定提示 `prompt`。`AgentSwitch` 会将入边消息与每条出边的 `prompt` 逐一组合，调用 `model` 判定（支持多条出边同时命中）。
- 使用示例：[语义分支示例](/zh/examples/conditional_branching)


## 自定义节点
### `CustomNode`
以回调函数自定义运行过程的节点，便于接入外部计算或规则。支持在初始化或后续通过 `set_forward` 设置处理函数。

- 构造参数：`name`、`forward`?、`memories`?、`tools`?、`pull_keys`?、`push_keys`? <br>
  - `forward`：自定义运行回调，**必须返回 `dict`**；若 `forward` 为 `None`，本节点会将输入原样透传到出边（输入同样是 `dict`）；<br>
  - `memories`、`tools`、`retrievers`：当前节点可用的记忆/工具/检索器列表（作为回调可选入参）；<br>
  - `pull_keys`、`push_keys`：含义同 `Node`（节点变量）。

- 相关方法：
  - `set_forward(forward_callback)`：设置回调函数。

- 回调函数：
  - 回调入参形态（按参数个数自动匹配，最多到 `self`）：
    1) `forward(input)`；
    2) `forward(input, attributes)`；
    3) `forward(input, attributes, memories)`；
    4) `forward(input, attributes, memories, tools)`；
    5) `forward(input, attributes, memories, tools, retrievers)`；
    6) `forward(input, attributes, memories, tools, retrievers, self)`；
  - 返回值：回调返回值将通过所有出边自动发送到下游节点（返回值必须是 `dict`）。
- 使用示例: [CustomNode 示例](/zh/examples/custom_node)
