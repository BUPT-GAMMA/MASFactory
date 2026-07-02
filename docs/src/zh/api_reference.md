# API Reference

本文档提供了 MASFactory 框架的完整 API 参考，包括所有核心类、方法和接口的详细说明。

::: tip 使用指南
- 点击左侧导航栏快速定位到相应模块
- 每个类都包含了详细的构造参数说明和使用示例
- 方法参数和返回值都有完整的类型注解
- 使用 <kbd>Ctrl</kbd> + <kbd>F</kbd> 快速搜索特定 API
:::

::: info 版本信息
当前文档对应 MASFactory v1.0.2
:::



## 核心模块

核心模块包含了 MASFactory 框架的基础组件，是构建任何工作流的必要组件。

### Node 类 {#node-class}

::: info 基础节点类
Node 是 MASFactory 中所有计算单元的抽象基类，提供了节点变量管理、消息传递和执行控制的基础功能。
:::

```python
class Node(ABC):
    def __init__(self,
                name: str,
                pull_keys: dict[str,dict|str] | None = None,
                push_keys: dict[str,dict|str] | None = None,
                attributes: dict[str,object] | None = None)
```

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `name` | `str` | - | 节点名称，用于在日志中标识该节点 |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | 从外层 Graph 提取的节点变量键及其描述 |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | 执行结束后回写到外层节点的节点变量键及其描述 |
| `attributes` | `dict[str,object] \| None` | `None` | 节点的初始节点变量 |

#### 重要属性

| 属性 | 类型 | 描述 |
|------|------|------|
| `name` | `str` | 节点名称（只读） |
| `in_edges` | `list[Edge]` | 所有入边的列表（只读） |
| `out_edges` | `list[Edge]` | 所有出边的列表（只读） |
| `input_keys` | `dict[str,dict\|str]` | 所有入边的键的合并结果（只读） |
| `output_keys` | `dict[str,dict\|str]` | 所有出边的键的合并结果（只读） |
| `is_ready` | `bool` | 检查节点是否准备好执行（只读） |
| `gate` | `Gate` | 节点的开闭状态（只读） |

#### 核心方法

##### execute()

```python
def execute(self, outer_env: dict[str,object] | None = None) -> None
```

执行节点的完整流程。

**执行步骤：**
1. 更新节点变量
2. 聚合所有入边的输入消息
3. 调用 `_forward` 方法处理输入
4. 将输出分发到所有出边
5. 更新节点变量

**参数：**
- `outer_env`: 外部环境的节点变量

##### _forward() *[抽象方法]*

```python
@abstractmethod
def _forward(self, input: dict[str,object]) -> dict[str,object]
```

节点的核心计算逻辑，子类必须实现。

**参数：**
- `input`: 由入边聚合得到的字典消息

**返回：**
- `dict[str,object]`: 将被分发到出边的字典消息

::: warning 节点变量处理规则
- `pull_keys` 为 None：继承外层节点的所有节点变量
- `pull_keys` 非 None：按指定字段从外层节点变量中抽取
- `pull_keys` 为空字典：不继承任何外层节点变量
:::

---

### Edge 类

::: info 边连接类
Edge 连接两个 Node，负责流程控制和消息传递。
:::

```python
class Edge:
    def __init__(self,
                sender: Node,
                receiver: Node,
                keys: dict[str,dict|str] | None = None)
```

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `sender` | `Node` | - | 发送消息的节点 |
| `receiver` | `Node` | - | 接收消息的节点 |
| `keys` | `dict[str,dict\|str] \| None` | `None` | 消息字段映射；默认为 `{\"message\": \"\"}` |

#### 重要属性

| 属性 | 类型 | 描述 |
|------|------|------|
| `keys` | `dict[str,dict\|str]` | 边的键描述映射（只读） |
| `is_congested` | `bool` | 检查边是否拥塞（有未接收的消息）（只读） |
| `gate` | `Gate` | 边的开闭状态（只读） |

#### 核心方法

##### send_message()

```python
def send_message(self, message: dict[str,object]) -> None
```

发送消息到边中，等待接收节点获取。

**参数：**
- `message`: 要发送的消息字典

**异常：**
- `RuntimeError`: 如果边已经拥塞
- `KeyError`: 如果消息缺少 `edge.keys` 所要求的字段

##### receive_message()

```python
def receive_message() -> dict[str,object]
```

从边中接收消息并清除拥堵状态。

**返回：**
- `dict[str,object]`: 接收到的消息字典

**异常：**
- `RuntimeError`: 如果边没有拥堵

### MessageFormatter 类

::: info 消息格式化器基类
MessageFormatter 是所有消息格式化器的抽象基类，负责两件事：
- 把模型输出文本解析成结构化 `dict`
- 把结构化 `dict` 渲染成提示词文本

当前公开 API 不再暴露 `Message` / `JsonMessage` 这类消息对象；框架内部统一以 `dict` 作为消息载体。
:::

```python
class MessageFormatter(ABC):
    def __init__(self)
```

#### 核心方法

##### format() *[抽象方法]*

```python
@abstractmethod
def format(self, message: str) -> dict
```

将模型输出的原始字符串解析为结构化 `dict`。

**参数：**
- `message`: 原始消息字符串

**返回：**
- `dict`: 解析后的结构化结果

**异常：**
- `NotImplementedError`: 子类必须实现此方法

##### dump() *[抽象方法]*

```python
@abstractmethod
def dump(self, message: dict) -> str
```

把结构化 `dict` 渲染为模型输入文本。

**参数：**
- `message`: 结构化消息字典

**返回：**
- `str`: 渲染后的文本

::: tip 补充
`MessageFormatter` 本身不是单例；只有 `StatelessFormatter` 这类无状态 formatter 才采用共享实例策略。
:::

---

### JsonMessageFormatter 类

::: info JSON 消息格式化器
JsonMessageFormatter 是严格 JSON 输出格式化器，用于把模型输出解析为 `dict`，并把 `dict` 序列化为 JSON 文本。
:::

```python
class JsonMessageFormatter(MessageFormatter):
    def __init__(self)
```

#### 核心方法

##### format()

```python
def format(self, message: str) -> dict
```

解析模型输出中的 JSON 对象，返回 `dict`。

**参数：**
- `message`: JSON 字符串消息

**返回：**
- `dict`: 解析后的 JSON 对象

**异常：**
- `ValueError`: 当消息中无法解析出合法 JSON 对象时抛出

**特性：**
- 会尝试去除代码块包装、提取最外层 JSON 子串，并做有限的容错修复
- 解析结果统一返回 `dict`

##### dump()

```python
def dump(self, message: dict) -> str
```

把结构化 `dict` 序列化为 JSON 字符串。

**参数：**
- `message`: 结构化消息字典

**返回：**
- `str`: JSON 文本

## 组件模块

### Agent 类

::: info 智能体节点
Agent 是图中的基本计算单元，封装了大语言模型、指令、工具和记忆模块。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `name` | `str` | - | Agent 在图中的唯一标识 |
| `instructions` | `str \| list[str]` | - | Agent 的指令，定义其行为和任务 |
| `model` | `Model` | - | 用于驱动 Agent 的模型适配器（必填，且为关键字参数） |
| `formatters` | `MessageFormatter \| list[MessageFormatter] \| None` | `None` | 输入/输出格式化器（单个 formatter 表示输入输出共用；两个 formatter 表示 `[in, out]`） |
| `max_retries` | `int \| None` | `3` | 模型调用失败时的最大重试次数 |
| `retry_delay` | `int \| None` | `1` | 退避重试的基础延迟系数 |
| `retry_backoff` | `int \| None` | `2` | 退避重试的指数基数 |
| `prompt_template` | `str \| list[str] \| None` | `None` | 提示模板 |
| `tools` | `list[Callable] \| None` | `None` | 工具函数列表 |
| `memories` | `list[Memory] \| None` | `None` | 记忆适配器列表；最多只能挂载一个 `HistoryProvider` 类型的 memory |
| `retrievers` | `list[Retrieval] \| None` | `None` | 检索适配器列表（RAG/MCP 等） |
| `skills` | `list[Skill] \| None` | `None` | 显式加载并附着在 directive 层的 skill 包 |
| `pull_keys` | `dict[str,dict|str] \| None` | `{}` | 可见/需要的节点变量键及说明 |
| `push_keys` | `dict[str,dict|str] \| None` | `{}` | 执行后写回的节点变量键及说明 |
| `model_settings` | `dict \| None` | `None` | 传递给模型的额外参数 |
| `role_name` | `str` | `None` | Agent 的角色名称 |
| `attributes` | `dict[str,object] \| None` | `None` | Agent 的本地初始节点变量 |
| `hide_unused_fields` | `bool` | `False` | 是否在 prompt 组装中隐藏未使用字段 |
| `reuse_attachment_tags` | `bool` | `True` | 对本轮 media 做去重；若历史返回富媒体 block，则相同附件可复用这些已有 tag |

#### 支持的 model_settings 参数

| 参数 | 类型 | 范围 | 描述 |
|------|------|------|------|
| `temperature` | `float` | [0.0, 2.0] | 温度参数，控制输出的随机性 |
| `max_tokens` | `int` | - | 最大输出 token 数 |
| `top_p` | `float` | [0.0, 1.0] | 核采样参数 |
| `stop` | `list[str]` | - | 停止生成的 token 列表 |
| `tool_choice` | `str \| dict` | provider-specific | 工具路由模式，或 provider 原生的 tool choice 配置 |

#### 使用示例

```python
agent = Agent(
    name="writer",
    model=model,
    instructions="Write concise JSON answers",
    tools=[web_search],
    memories=[conversation_memory],
    pull_keys={"topic": "当前主题"},
    push_keys={"last_answer": "最近一次回答"}
)
```

::: tip 工具调用处理
当提供工具时，模型可能产生工具调用响应。Agent 会自动调用并回填结果，然后再次询问模型直到返回最终内容。
:::

::: info 调用装配
`Agent.observe(...)` 会把 prompt / messages / tools 的装配委托给 `RequestAssembler`。
运行时会保留 directives（instructions + skills）、conversation history、passive resource context 与 actions/tools 的独立语义层。
:::

---

### BaseGraph 类

::: info 基础图类
BaseGraph 是所有图类型的基础，提供节点管理和边连接的基本功能。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `name` | `str` | - | 图的名称，用于标识此图 |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | 从外层提取的节点变量键及其描述 |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | 执行后回写的节点变量键及其描述 |
| `attributes` | `dict[str,object] \| None` | `None` | 图的初始节点变量 |
| `build_func` | `Callable \| None` | `None` | 可选构建回调，在子节点 `build()` 前执行（签名：`(graph: BaseGraph) -> None`） |

#### 核心方法

##### create_node()

```python
def create_node(self, cls: type[Node] | NodeTemplate, *args, **kwargs) -> Node
```

在图中创建一个新节点。

**参数：**
- `cls`: 要创建的节点类型，必须是 Node 的子类
- `*args`: 传递给节点构造函数的位置参数
- `**kwargs`: 传递给节点构造函数的关键字参数

**返回：**
- `Node`: 创建的节点实例

**异常：**
- `TypeError`: 如果提供的类不是 `Node` 子类或 `NodeTemplate`
- `ValueError`: 如果节点名非法/重复、或为受限类型（如 RootGraph / SingleAgent）

**限制：**
- 不能创建 RootGraph 类型的节点
- 不能创建 SingleAgent 类型的节点

##### create_edge()

```python
def create_edge(self,
               sender: Node,
               receiver: Node,
               keys: dict[str, dict|str] | None = None) -> Edge
```

在两个节点之间创建一条边。

**参数：**
- `sender`: 发送消息的节点
- `receiver`: 接收消息的节点
- `keys`: 定义消息字段映射的键字典

**返回：**
- `Edge`: 创建的边实例

**异常：**
- `ValueError`: 如果节点不在图中，或创建边会形成循环、重复边

**安全检查：**
- 环路检测
- 重复边检测

##### build()

```python
def build() -> None
```

构建图及其所有子节点。

##### check_built()

```python
def check_built() -> bool
```

检查图是否已构建。

**返回：**
- `bool`: 若图及其所有子节点均已构建返回 True

---

### LogicSwitch 类 {#logic-switch-class}

::: info 逻辑分支节点
LogicSwitch 是一个基于条件将输入路由到不同输出边的节点，类似于编程语言中的 switch 语句。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `name` | `str` | - | 节点的名称 |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | 从外层提取的节点变量键及其描述 |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | 执行后回写的节点变量键及其描述 |
| `attributes` | `dict[str,object] \| None` | `None` | 节点的本地初始节点变量 |
| `routes` | `dict[str, Callable] \| None` | `None` | 可选的声明式路由规则：`{receiver_node_name: predicate}`（会在 `build()` 时编译为边绑定） |

#### 核心方法

##### condition_binding() {#logic-switch-binding}

```python
def condition_binding(self, 
                     condition: Callable[[dict, dict[str,object]], bool], 
                     out_edge: Edge) -> None
```

将一个输出边与一个条件回调函数绑定。

**参数：**
- `condition`: 接收聚合后的输入消息（dict）与节点变量（attributes）并返回布尔值的函数
- `out_edge`: 要与条件关联的输出边

**异常：**
- `ValueError`: 如果该边已被绑定
- `ValueError`: 如果 out_edge 不在节点的输出边中

#### 使用示例

```python
# 创建逻辑开关
switch = graph.create_node(LogicSwitch, "content_router")

# 创建两个目标节点
positive_handler = graph.create_node(Agent, 
    name="positive_handler",
    model=model,
    instructions="处理积极内容"
)

negative_handler = graph.create_node(Agent,
    name="negative_handler", 
    model=model,
    instructions="处理消极内容"
)

# 创建输出边
e1 = graph.create_edge(switch, positive_handler, {"content": "内容"})
e2 = graph.create_edge(switch, negative_handler, {"content": "内容"})

# 绑定条件
switch.condition_binding(
    lambda message, attrs: "positive" in str(message.get("content", "")).lower(), 
    e1
)
switch.condition_binding(
    lambda message, attrs: "negative" in str(message.get("content", "")).lower(), 
    e2
)
```

::: tip 路由逻辑
- 当 LogicSwitch 执行时，它会评估每个条件
- 消息会被发送到所有条件为真的边
- 支持多路输出，一个输入可以同时发送到多个输出边
:::

---

### Loop 类 {#loop-class}

::: info 循环图结构
Loop 是一个实现循环逻辑的特殊图结构，允许重复执行子图直到满足终止条件。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `name` | `str` | - | 循环的名称 |
| `max_iterations` | `int` | `10` | 循环的最大迭代次数 |
| `model` | `Model \| None` | `None` | 用于评估终止条件的 LLM 适配器 |
| `terminate_condition_prompt` | `str \| None` | `None` | 用于 LLM 评估终止条件的提示 |
| `terminate_condition_function` | `Callable \| None` | `None` | 终止条件函数（优先级高于 `terminate_condition_prompt`） |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | 从外层提取的节点变量键及其描述 |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | 执行后回写的节点变量键及其描述 |
| `attributes` | `dict[str,object] \| None` | `None` | 循环图的初始节点变量 |
| `initial_messages` | `dict[str,object] \| None` | `None` | 循环启动时注入到内部控制流的初始消息 |
| `edges` | `list[tuple] \| None` | `None` | 声明式边列表（形如 `(sender, receiver[, keys])`） |
| `nodes` | `list[tuple] \| None` | `None` | 声明式节点列表（形如 `(name, NodeTemplate)` 或更高阶结构） |
| `build_func` | `Callable \| None` | `None` | 可选构建回调（签名：`(graph: BaseGraph) -> None`） |

#### 内部结构

Loop 内部包含特殊的控制节点：

- **Controller**：控制最大循环次数并在每次循环开始时判断结束条件
- **TerminateNode**：用于在循环进行中退出循环（相当于 break 语句）

#### 特殊方法

##### edge_from_controller() {#loop-edge-from}

```python
def edge_from_controller(self, 
                        receiver: Node, 
                        keys: dict[str, dict|str] | None = None) -> Edge
```

创建从内部 Controller 到指定节点的边。

##### edge_to_controller() {#loop-edge-to}

```python
def edge_to_controller(self,
                      sender: Node,
                      keys: dict[str, dict|str] | None = None) -> Edge
```

创建从指定节点到内部 Controller 的边。

##### edge_to_terminate_node() {#loop-edge-terminate}

```python
def edge_to_terminate_node(self,
                          sender: Node,
                          keys: dict[str, dict|str] | None = None) -> Edge
```

创建从指定节点到 TerminateNode 的边，用于提前退出循环。

#### 使用示例

```python
# 创建循环图
loop = graph.create_node(Loop,
    name="data_processing_loop",
    max_iterations=5,
    model=model,
    terminate_condition_prompt="检查是否已达到预期结果"
)

# 在循环内创建处理节点
processor = loop.create_node(Agent,
    name="processor",
    model=model,
    instructions="处理数据并检查是否需要继续"
)

# 建立循环连接
loop.edge_from_controller(processor, {"data": "要处理的数据"})
loop.edge_to_controller(processor, {"result": "处理结果"})
```

::: warning 循环连接规则
1. Loop 内的节点必须通过 `edge_from_controller` 和 `edge_to_controller` 连接到内部控制器
2. 不连接到控制器的节点不会参与循环执行
3. `edge_to_terminate_node` 是可选的，用于提前退出循环
4. 循环会在达到最大迭代次数或满足终止条件时结束
:::

---

### Graph 类

::: info 标准图实现
Graph 是基础图的标准实现，提供入口和出口节点，支持构建复杂的节点网络。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `name` | `str` | - | 图的名称，用于日志标识 |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | 节点变量的键值描述映射 |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | 更新节点变量的键值对 |
| `attributes` | `dict[str,object] \| None` | `None` | 默认节点变量 |
| `edges` | `list[tuple] \| None` | `None` | 声明式边列表（形如 `(sender, receiver[, keys])`） |
| `nodes` | `list[tuple] \| None` | `None` | 声明式节点列表（形如 `(name, NodeTemplate)` 或更高阶结构） |
| `build_func` | `Callable \| None` | `None` | 可选构建回调（签名：`(graph: BaseGraph) -> None`） |

#### 核心方法

**edge_from_entry(receiver, keys)**

创建从入口节点到指定节点的边。

**edge_to_exit(sender, keys)**

创建从指定节点到出口节点的边。

#### 特性

- **入口/出口节点**：自动创建 EntryNode 和 ExitNode
- **轮询执行**：通过轮询就绪节点执行，直至出口就绪
- **灵活连接**：支持任意复杂的节点连接模式

---

::: warning 已移除组件
`AutoGraph` 已从当前版本的 MASFactory 中移除。
:::

---

### RootGraph 类

::: info 根图实现
RootGraph 是最外层的图，可被用户直接实例化和调用。
:::

```python
class RootGraph(Graph):
    def __init__(self,
                name: str,
                attributes: dict[str,object] | None = None,
                edges: list[tuple[str,str] | tuple[str,str,dict[str,dict|str]]] | None = None,
                nodes: list[tuple[str, NodeTemplate]] | None = None)
```

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `name` | `str` | - | 图的名称 |
| `attributes` | `dict[str,object] \| None` | `None` | 图的初始节点变量 |
| `edges` | `list[tuple] \| None` | `None` | 声明式边列表（形如 `(sender, receiver[, keys])`） |
| `nodes` | `list[tuple[str, NodeTemplate]] \| None` | `None` | 声明式节点列表（`[(name, NodeTemplate), ...]`） |

#### 核心方法

**invoke(input, attributes=None)**

开始执行 RootGraph。

- `input` (dict): 系统输入，需与入边 keys 对齐
- `attributes` (dict | None): 运行时注入并合并到图属性的变量
- 返回: tuple[dict, dict] - `(output_dict, attributes_dict)`

#### 使用示例

```python
graph = RootGraph("demo")
# ... 创建节点/边 ...
graph.build()
out, attrs = graph.invoke({"question": "hi"})
```

---

### SingleAgent 类

::: info 单一代理
SingleAgent 是一个简化的、独立的 Agent，用于执行单个任务，可独立于 Graph 使用。
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
                role_name: str | None = None,
                formatters: list[MessageFormatter] | MessageFormatter | None = None,
                skills: list[Skill] | None = None,
                attributes: dict[str, object] | None = None,
                hide_unused_fields: bool = False,
                reuse_attachment_tags: bool = True)
```

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `name` | `str` | - | 节点名称 |
| `model` | `Model` | - | 模型适配器 |
| `instructions` | `str \| list[str]` | - | Agent 指令（system prompt） |
| `prompt_template` | `str \| list[str] \| None` | `None` | prompt 模板（user prompt） |
| `max_retries` | `int` | `3` | 模型调用失败时的最大重试次数 |
| `retry_delay` | `int` | `1` | 退避重试的基础延迟系数 |
| `retry_backoff` | `int` | `2` | 退避重试的指数基数 |
| `tools` | `list[Callable]` | `None` | 可用工具列表 |
| `memories` | `list[Memory] \| None` | `None` | 记忆模块列表；最多只能挂载一个 `HistoryProvider` 类型的 memory |
| `retrievers` | `list[Retrieval] \| None` | `None` | 检索适配器列表（RAG/MCP 等） |
| `model_settings` | `dict \| None` | `None` | 模型调用参数 |
| `role_name` | `str \| None` | `None` | 角色名称 |
| `formatters` | `list[MessageFormatter] \| MessageFormatter \| None` | `None` | 可选输入/输出格式化器 |
| `skills` | `list[Skill] \| None` | `None` | 可选的已加载 skill 包 |
| `attributes` | `dict[str, object] \| None` | `None` | 可选默认本地 attributes |
| `hide_unused_fields` | `bool` | `False` | 是否隐藏未被模板消费的字段 |
| `reuse_attachment_tags` | `bool` | `True` | 对本轮 media 做去重；若历史返回富媒体 block，则相同附件可复用这些已有 tag |

#### 特性

- **独立使用**：可独立于图结构使用
- **简化接口**：提供更简单的 `invoke` 方法
- **完整功能**：支持工具调用、记忆管理等完整功能

---

### DynamicAgent 类

::: info 动态代理
DynamicAgent 可根据输入动态调整指令的 Agent，支持运行时行为配置。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `name` | `str` | - | 节点名称 |
| `model` | `Model` | - | 模型适配器 |
| `default_instructions` | `str` | `""` | 初始化时使用的默认指令；运行期通常由 `instruction_key` 对应字段覆盖 |
| `instruction_key` | `str` | `"instructions"` | 动态指令的键名 |
| `formatters` | `MessageFormatter \| list[MessageFormatter] \| None` | `None` | 输入/输出格式化器（与 Agent 语义一致） |
| `max_retries` | `int` | `3` | 模型调用失败时的最大重试次数 |
| `retry_delay` | `int` | `1` | 退避重试的基础延迟系数 |
| `retry_backoff` | `int` | `2` | 退避重试的指数基数 |
| `pull_keys` | `dict[str,dict|str] \| None` | `{}` | 可见/需要的节点变量键及说明 |
| `push_keys` | `dict[str,dict|str] \| None` | `{}` | 执行后写回的节点变量键及说明 |
| `memories` | `list[Memory] \| None` | `None` | 记忆适配器列表 |
| `retrievers` | `list[Retrieval] \| None` | `None` | 检索适配器列表（RAG/MCP 等） |
| `attributes` | `dict[str,object] \| None` | `None` | Agent 的本地初始节点变量 |

#### 特性

- **动态指令**：运行时会从输入消息里读取 `instruction_key` 对应字段，并覆盖本轮指令
- **回退语义**：如果该字段缺失，则继续使用 `default_instructions`
- **灵活配置**：支持自定义指令键名
- **完整功能**：继承 Agent 的所有功能

---

## Skills {#skills}

MASFactory Skills 是基于 Anthropic 风格 `SKILL.md` 的显式目录包。
它们由用户在代码中加载，并通过 `Agent(..., skills=[...])` 挂载到 Agent 上。

### Skill 类

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

解析后的 Anthropic 风格 Skill 包对象，可被 MASFactory Agent 复用。

#### 重要字段

| 字段 | 类型 | 描述 |
|------|------|------|
| `name` | `str` | Skill 名称；如果 frontmatter 缺失 `name`，会回退到目录名。 |
| `description` | `str \| None` | frontmatter 中的可选描述。 |
| `body` | `str` | 从 `SKILL.md` 中提取出的主体 markdown 指令。 |
| `skill_dir` | `Path` | Skill 包的根目录。 |
| `skill_md_path` | `Path` | 被解析的 `SKILL.md` 绝对路径。 |
| `frontmatter` | `dict[str, Any]` | 解析后的 YAML frontmatter 映射。 |
| `examples` | `list[Path]` | 在 `examples/` 中发现的 supporting files。 |
| `templates` | `list[Path]` | 在 skill 根目录发现的 markdown 模板文件。 |
| `references` | `list[Path]` | 包内发现的其他 supporting files。 |
| `scripts` | `list[Path]` | 在 `scripts/` 中发现的文件。 |
| `raw_markdown` | `str` | `SKILL.md` 的原始文本内容。 |

#### 重要属性

| 属性 | 类型 | 描述 |
|------|------|------|
| `source_path` | `str` | 规范化后的 skill 根目录路径。 |

#### 重要方法

| 方法 | 返回值 | 描述 |
|------|------|------|
| `metadata()` | `dict[str, object]` | 给 Agent / visualizer 使用的稳定元数据。 |
| `render_supporting_files(label, paths)` | `str \| None` | 以有边界的方式渲染 supporting files 进入 prompt。 |
| `render_section()` | `str` | 渲染单个完整 skill 指令区块。 |

### SkillSet 类

```python
@dataclass(frozen=True)
class SkillSet:
    skills: list[Skill] = field(default_factory=list)
```

供 Agent 消费的 skill 侧组合视图。
它负责 skill 渲染与 metadata 组合，因此 `Agent` 不需要直接读取 skill 文件。

#### 核心方法

- `render_instructions() -> str`：渲染 `[Loaded Skills]` 区块
- `compose(base_instructions: str) -> str`：把 skill 渲染结果追加到基础 instructions 后
- `media_assets -> list[MediaAsset]`：返回 skill 声明的静态 media 资源
- `metadata() -> list[dict[str, object]]`：返回已加载 skills 的稳定元数据

### load_skill()

```python
def load_skill(path: str | Path) -> Skill
```

从目录中加载一个 Anthropic 风格 Skill 包。

**参数：**
- `path`：Skill 目录路径，目录中必须包含 `SKILL.md`

**返回：**
- `Skill`：包含规范化路径和 supporting files 信息的解析结果

**异常：**
- `SkillNotFoundError`：目录不存在，或缺少 `SKILL.md`
- `InvalidSkillPackageError`：路径存在，但不是合法的 skill 包目录
- `SkillParseError`：`SKILL.md` 无法读取或无法解析为合法 Skill 定义

**示例：**

```python
from masfactory import load_skill

paper_summary = load_skill("./skills/paper-summary")
```

### load_skills()

```python
def load_skills(paths: Iterable[str | Path]) -> list[Skill]
```

按给定顺序批量加载多个 Skill 包。

**参数：**
- `paths`：Skill 目录路径迭代器

**返回：**
- `list[Skill]`：保持输入顺序的 Skill 列表

**异常：**
- `SkillNotFoundError`：任一目录不存在，或缺少 `SKILL.md`
- `InvalidSkillPackageError`：任一路径不是合法的 skill 包目录
- `SkillParseError`：任一 `SKILL.md` 无法解析

**说明：**
- `load_skills()` 采用 fail-fast 语义，遇到第一个非法 skill 包就立即停止

**示例：**

```python
from masfactory import load_skills

paper_summary, review_writing = load_skills([
    "./skills/paper-summary",
    "./skills/review-writing",
])
```

### Skill 相关异常

#### SkillError

MASFactory Skills API 抛出的公共异常基类。

#### SkillNotFoundError

当目标 skill 目录不存在，或缺少必要的 `SKILL.md` 文件时抛出。

#### InvalidSkillPackageError

当目标路径存在，但不符合预期的 skill 包结构时抛出。

#### SkillParseError

当 `SKILL.md` 存在，但无法解析成合法的 skill 定义时抛出。

---

### AgentSwitch 类

::: info 代理路由器
AgentSwitch 是一种基于 LLM 的 Switch 节点：为每条出边绑定自然语言条件，由模型评估输入消息是否满足条件并选择路由。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `name` | `str` | - | 代理名称 |
| `model` | `Model` | - | 用于评估条件的 LLM 适配器 |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | 从外层提取的节点变量键及其描述 |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | 执行后回写的节点变量键及其描述 |
| `attributes` | `dict[str,object] \| None` | `None` | 节点的本地初始节点变量 |
| `routes` | `dict[str,str] \| None` | `None` | 可选的声明式路由规则：`{receiver_node_name: condition_text}`（会在 `build()` 时编译为边绑定） |

#### 核心方法

**condition_binding(condition, edge)**

为输出边绑定条件描述。

- `condition` (str): 条件描述文本
- `edge` (Edge): 要绑定的输出边

#### 使用示例

```python
sw = AgentSwitch("router", model)
e1 = graph.create_edge(sw, agent1, {"x": "处理方案A"})
e2 = graph.create_edge(sw, agent2, {"x": "处理方案B"})
sw.condition_binding("答案包含关键字 yes", e1)
sw.condition_binding("答案包含关键字 no", e2)
```

---

### CustomNode 类

::: info 自定义节点
CustomNode 允许用户通过回调函数实现自定义的计算逻辑，是扩展 MASFactory 功能的重要方式。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `name` | `str` | - | 节点的名称 |
| `forward` | `Callable \| None` | `None` | 自定义的 forward 函数 |
| `memories` | `list[Memory] \| None` | `None` | 当前节点可用的记忆 |
| `tools` | `list[Callable] \| None` | `None` | 当前节点可用的工具 |
| `retrievers` | `list[Retrieval] \| None` | `None` | 当前节点可用的检索适配器（RAG/MCP 等） |
| `pull_keys` | `dict[str,dict|str] \| None` | `None` | 从外层提取的节点变量键及其描述 |
| `push_keys` | `dict[str,dict|str] \| None` | `None` | 更新到节点变量的键值描述 |
| `attributes` | `dict[str,object] \| None` | `None` | 节点的本地初始节点变量 |

#### Forward 回调函数

CustomNode 的核心是 forward 回调函数，它定义了节点的计算逻辑。回调函数支持多种参数组合：

```python
# 1 个参数：仅输入数据
def simple_forward(input_data):
    return {"result": f"Processed: {input_data}"}

# 2 个参数：输入数据 + 节点变量
def forward_with_attributes(input_data, attributes):
    count = attributes.get("count", 0) + 1
    attributes["count"] = count
    return {"result": f"Processing #{count}: {input_data}"}

# 3 个参数：输入数据 + 节点变量 + 记忆
def forward_with_memory(input_data, attributes, memories):
    if memories:
        memories[0].insert("last_input", str(input_data))
    return {"result": f"Processed with memory: {input_data}"}

# 4 个参数：输入数据 + 节点变量 + 记忆 + 工具
def forward_with_tools(input_data, attributes, memories, tools):
    # 可以调用工具
    return {"result": f"Processed with tools: {input_data}"}

# 5 个参数：输入数据 + 节点变量 + 记忆 + 工具 + 检索适配器
def forward_with_retrievers(input_data, attributes, memories, tools, retrievers):
    return {"result": f"Processed with retrievers: {input_data}"}

# 6 个参数：输入数据 + 节点变量 + 记忆 + 工具 + 检索适配器 + 节点对象
def forward_full(input_data, attributes, memories, tools, retrievers, node):
    return {"result": f"Node {node.name} processed: {input_data}"}
```

#### 核心方法

##### set_forward()

```python
def set_forward(self, forward_callback: Callable) -> None
```

动态设置自定义 forward 函数。

**参数：**
- `forward_callback`: 回调函数，参数结构同构造函数中的 forward

#### 使用示例

```python
def custom_processor(input_data, attributes, memories, tools, retrievers, node):
    """
    自定义处理函数示例
    """
    # 实现自定义逻辑
    result = perform_custom_logic(input_data)
    
    # 可以访问和修改节点变量
    attributes["processing_count"] = attributes.get("processing_count", 0) + 1
    
    # 可以使用记忆和工具
    if memories:
        memories[0].insert("last_input", str(input_data))
    
    return {"result": result}

# 创建自定义节点
custom_node = graph.create_node(CustomNode,
    name="custom_processor",
    forward=custom_processor,
    memories=[history_memory],
    tools=[search_tool]
)

# 或者动态设置回调
custom_node = graph.create_node(CustomNode, name="dynamic_node")
custom_node.set_forward(custom_processor)
```

::: warning 回调函数参数
- 若未提供 forward 函数，节点将输入原样透传给输出
- 回调函数的参数数量决定了传递给函数的参数个数
- 支持 1-6 个参数的回调函数
:::

---

## 模型 Model

### Model 类

::: info 模型适配器基类
Model 是与各种大语言模型交互的统一接口的抽象基类。
:::

```python
class Model(ABC):
    def __init__(self,
                model_name: str | None = None,
                invoke_settings: dict | None = None,
                *args, **kwargs)
```

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `model_name` | `str \| None` | `None` | 模型名称 |
| `invoke_settings` | `dict \| None` | `None` | 默认调用设置 |

#### 重要属性

| 属性 | 类型 | 描述 |
|------|------|------|
| `model_name` | `str` | 模型的名称（只读） |
| `description` | `object` | 模型的描述信息（只读） |

#### 核心方法

##### invoke() *[抽象方法]*

```python
@abstractmethod
def invoke(self,
          messages: list[dict],
          tools: list[dict] | None,
          settings: dict | None = None,
          **kwargs) -> dict
```

调用大语言模型并获取响应。

**参数：**
- `messages`: 包含对话历史的列表
- `tools`: 可选的工具列表
- `settings`: 特定于模型的参数
- `**kwargs`: 其他参数

**返回：**
- `dict`: 包含响应类型和内容的字典

**返回格式：**
```python
# 内容响应
{"type": ModelResponseType.CONTENT, "content": "..."}

# 工具调用响应
{"type": ModelResponseType.TOOL_CALL, "content": [
    {"id": str|None, "name": str, "arguments": dict}, ...
]}
```

---

### OpenAIModel 类

::: info OpenAI Responses 模型适配器
`OpenAIModel` 使用 OpenAI Responses API，并支持包括 PDF 在内的多模态输入。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `model_name` | `str` | - | OpenAI 模型名称（如 "gpt-4o-mini"） |
| `api_key` | `str` | - | OpenAI API 密钥 |
| `base_url` | `str \| None` | `None` | API 基础 URL |
| `invoke_settings` | `dict \| None` | `None` | 默认调用设置 |

#### 常用用法

通常建议从环境变量中读取密钥与模型名，并显式传入适配器：

```python
import os
from masfactory import OpenAIModel

model = OpenAIModel(
    model_name=os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL") or None,
)
```

#### 支持的设置参数

| 参数 | 类型 | 范围 | 描述 |
|------|------|------|------|
| `temperature` | `float` | [0.0, 2.0] | 控制输出随机性 |
| `max_tokens` | `int` | - | 最大 token 数 |
| `top_p` | `float` | [0.0, 1.0] | 核采样参数 |
| `stop` | `list[str]` | - | 停止 token 列表 |

---

### LegacyOpenAIModel 类

::: info OpenAI Chat Completions 模型适配器
`LegacyOpenAIModel` 使用 Chat Completions API 对接 OpenAI 兼容接口，且不支持 PDF 输入。
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

### AnthropicModel 类

::: info Anthropic 模型适配器
AnthropicModel 实现了与 Anthropic Claude API 交互的模型适配器。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `model_name` | `str` | - | Anthropic 模型名称（如 "claude-3-opus-20240229"） |
| `api_key` | `str` | - | Anthropic API 密钥 |
| `base_url` | `str \| None` | `None` | API 基础 URL（可选） |
| `invoke_settings` | `dict \| None` | `None` | 默认调用设置 |

#### 支持的模型

- `claude-3-opus-20240229`
- `claude-3-sonnet-20240229`
- `claude-3-haiku-20240307`

> 这些仅是示例，不代表完整或实时的 provider 模型列表。

---

### GeminiModel 类

::: info Google Gemini 模型适配器
GeminiModel 使用 `google-genai` SDK 与 Google Gemini 交互。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `model_name` | `str` | - | Gemini 模型名称（如 "gemini-pro"） |
| `api_key` | `str` | - | Google AI API 密钥 |
| `base_url` | `str \| None` | `None` | API 基础 URL（可选） |
| `invoke_settings` | `dict \| None` | `None` | 默认调用设置 |

#### 支持的模型

- `gemini-pro`
- `gemini-pro-vision`
- `gemini-1.5-pro`

> 这些仅是示例，不代表完整或实时的 provider 模型列表。

---
## 记忆系统
### Memory 类（ContextBlock 注入）

::: info Memory = 可写入的上下文源
在 MASFactory 中，Memory 不再提供旧式的 `query(...) -> str` 接口。  
Memory 作为上下文源（ContextProvider）通过 `get_blocks(...)` 产出结构化 `ContextBlock`，
由 Agent 在 Observe 阶段注入到 user prompt 的 `CONTEXT` 字段。
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

#### 重要语义

- `context_label`：上下文源名称（用于渲染与追溯）
- `passive=True`：自动注入到 `CONTEXT`
- `active=True`：作为工具供模型按需检索（`retrieve_context`）

更完整的上下文适配与示例见：[`/zh/guide/context_adapters`](/zh/guide/context_adapters)。

---

### HistoryMemory 类（对话历史）

::: info 历史记忆实现
`HistoryMemory` 用于保存对话历史，并以 chat messages 的形式插入到模型 `messages` 中。  
它不会产出 `ContextBlock`（`get_blocks(...)` 恒为空）。一个 `Agent` 最多只能挂载一个 `HistoryProvider` 类型的 memory。它也可以在返回 `get_messages(...)` 时可选地合并重复历史 media；这个行为由 memory 自己的 `merge_historical_media` 参数控制。当开启时，重复附件会以索引标签引用形式返回，而不是重复 media block。
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

#### top_k 约定

- `top_k=-1`：使用实例默认值（`__init__` 里的 `top_k`）
- `top_k=0`：尽可能多返回（受 `memory_size` 限制）
- `top_k<0`：返回空

#### 使用示例

```python
from masfactory import HistoryMemory

memory = HistoryMemory(top_k=10, memory_size=50)
memory.insert("user", "你好，我想了解 MASFactory")
memory.insert("assistant", "当然可以。")

print(memory.get_messages(top_k=2))
```

> 当 `HistoryMemory` 挂到 `Agent(memories=[...])` 上时，Agent 会自动把 `get_messages(...)`
> 的结果插入到 `messages` 里（system 与 user 之间）。

---

### VectorMemory 类（语义记忆）

::: info 向量记忆
`VectorMemory` 通过 embeddings + 余弦相似度，从历史写入中挑选相关条目，作为 `ContextBlock` 注入到 `CONTEXT`。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `embedding_function` | `Callable[[str], np.ndarray]` | - | 文本转 embedding 的函数 |
| `top_k` | `int` | `10` | 作为上下文注入时的默认返回条数 |
| `query_threshold` | `float` | `0.8` | 相似度阈值 |
| `memory_size` | `int` | `20` | 最大保存条目数 |
| `context_label` | `str` | `"SEMANTIC_KNOWLEDGE"` | 上下文源名称 |

#### 说明

- `VectorMemory.get_blocks(...)` 使用 `ContextQuery.query_text` 作为检索 query（由 Agent 从输入字段尽力提取）。
- 返回的 `ContextBlock.score` 为相似度分数，便于调试。

::: warning 旧版提示
如果你在旧文档/旧代码中看到 `KeyValueMemory / SummaryMemory / StorageVectorMemory` 等类型：
它们不属于当前版本 API（可能已移除或迁移）。
:::

---

## 枚举类型

### ModelResponseType

::: info 模型响应类型
定义大语言模型响应的类型枚举。
:::

```python
class ModelResponseType(Enum):
    CONTENT = "content"      # 纯文本内容
    TOOL_CALL = "tool_call"  # 工具调用请求
```

#### 枚举值

| 值 | 取值 | 描述 |
|----|----|------|
| `TOOL_CALL` | `"tool_call"` | 表示模型的响应是一个或多个工具调用请求 |
| `CONTENT` | `"content"` | 表示模型的响应是纯文本内容 |

### Gate

::: info 门控状态
定义节点和边的开闭状态。
:::

```python
class Gate(Enum):
    CLOSED = "CLOSED"  # 关闭状态
    OPEN = "OPEN"      # 打开状态
```

## 工具系统

### ToolAdapter 类

::: info 工具适配器
ToolAdapter 管理一组可调用的工具函数，并能将其转换为 LLM 所需的 JSON Schema 格式。
:::

```python
class ToolAdapter:
    def __init__(self, tools: list[Callable])
```

#### 构造参数

| 参数 | 类型 | 描述 |
|------|------|------|
| `tools` | `list[Callable]` | 可调用函数组成的列表，作为工具管理 |

#### 重要属性

##### details

```python
@property
def details(self) -> dict
```

生成所有已注册工具的详细信息，格式为 JSON Schema。

**返回：**
- `dict`: 包含所有工具描述的列表，每个描述包含 "name", "description", 和 "parameters"

**特性：**
- 自动内省函数签名和 docstring
- 支持 Optional/Union/List/Dict 等类型映射
- 构建符合 LLM 函数调用规范的描述

#### 核心方法

##### call()

```python
def call(self, name: str, arguments: dict) -> str
```

根据名称和参数调用工具。

**参数：**
- `name`: 要调用的工具的名称（函数名）
- `arguments`: 传递给工具函数的参数字典

**返回：**
- `str`: 工具函数执行后的返回值

#### 工具函数规范

工具函数需要遵循以下规范以确保正确的 JSON Schema 生成：

```python
def web_search(query: str, max_results: int = 5) -> str:
    """
    在网络上搜索信息
    
    Args:
        query (str): 搜索关键词
        max_results (int): 最大结果数量，默认为5
        
    Returns:
        str: 搜索结果的文本描述
    """
    # 实现搜索逻辑
    results = perform_web_search(query, max_results)
    return format_search_results(results)

def calculate_statistics(numbers: list[float]) -> dict:
    """
    计算数值列表的统计信息
    
    Args:
        numbers (list[float]): 数值列表
        
    Returns:
        dict: 包含平均值、最大值、最小值等统计信息
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

#### 使用示例

```python
# 定义工具函数
tools = [web_search, calculate_statistics]

# 创建工具适配器
tool_adapter = ToolAdapter(tools)

# 获取工具详细信息（JSON Schema 格式）
tool_details = tool_adapter.details

# 手动调用工具
result = tool_adapter.call("web_search", {
    "query": "人工智能", 
    "max_results": 3
})

# 在 Agent 中使用工具
agent = graph.create_node(Agent,
    name="tool_agent",
    model=model,
    instructions="你是一个具有多种工具能力的助手",
    tools=tools
)
```

#### 支持的类型映射

| Python 类型 | JSON Schema 类型 |
|-------------|------------------|
| `str` | `{"type": "string"}` |
| `int` | `{"type": "integer"}` |
| `float` | `{"type": "number"}` |
| `bool` | `{"type": "boolean"}` |
| `list[T]` | `{"type": "array", "items": <T的映射>}` |
| `dict` | `{"type": "object"}` |
| `Optional[T]` | Union 类型处理 |
| `Union[T1, T2, ...]` | `{"anyOf": [<T1映射>, <T2映射>, ...]}` |

::: tip 工具函数最佳实践
1. **完整的类型注解**：确保所有参数和返回值都有类型注解
2. **详细的 docstring**：提供清晰的函数描述和参数说明
3. **错误处理**：在工具函数中添加适当的错误处理
4. **返回格式一致**：保持工具函数返回格式的一致性
:::

## 检索模块（RAG / Retrieval）

### Retrieval 类（ContextBlock 注入）

::: info Retrieval = 只读的上下文源
在 MASFactory 中，检索器（RAG）通过 `get_blocks(...)` 返回结构化 `ContextBlock`，
由 Agent 在 Observe 阶段注入到 user prompt 的 `CONTEXT` 字段。
:::

```python
class Retrieval(ContextProvider, ABC):
    def __init__(self, context_label: str, *, passive: bool = True, active: bool = False)
    def get_blocks(self, query: ContextQuery, *, top_k: int = 8) -> list[ContextBlock]
```

#### top_k 约定（内置实现）

- `top_k=0`：尽可能多返回
- `top_k<0`：返回空

更完整的上下文注入与 active 检索工具见：[`/zh/guide/context_adapters`](/zh/guide/context_adapters)。

---

### VectorRetriever 类

::: info 向量检索实现
VectorRetriever 基于向量嵌入和相似度搜索来检索相关文档。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `documents` | `dict[str, str]` | - | 文档ID到文档内容的映射 |
| `embedding_function` | `Callable[[str], np.ndarray]` | - | 文本转换为向量嵌入的函数 |
| `similarity_threshold` | `float` | `0.7` | 相似度阈值 |
| `context_label` | `str` | `"VECTOR_RETRIEVER"` | 上下文源名称 |

#### 特性

- **向量嵌入**：预计算所有文档的向量嵌入
- **余弦相似度**：使用余弦相似度计算查询与文档的相关性
- **高效检索**：基于向量相似度进行快速检索

---

### FileSystemRetriever 类

::: info 文件系统检索实现
FileSystemRetriever 从文件系统加载文档并支持向量检索，具备缓存功能。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `docs_dir` | `str` | - | 文档目录路径 |
| `embedding_function` | `Callable[[str], np.ndarray]` | - | 文本转换为向量嵌入的函数 |
| `file_extension` | `str` | `".txt"` | 要加载的文件扩展名 |
| `similarity_threshold` | `float` | `0.7` | 相似度阈值 |
| `cache_path` | `str \| Path \| None` | `None` | 缓存嵌入的文件路径 |
| `context_label` | `str` | `"FILESYSTEM_RETRIEVER"` | 上下文源名称 |

#### 特性

- **文件系统扫描**：自动扫描指定目录下的文档文件
- **缓存机制**：支持嵌入向量的持久化缓存
- **灵活配置**：支持多种文件扩展名和目录结构

---

### SimpleKeywordRetriever 类

::: info 关键词检索实现
SimpleKeywordRetriever 使用关键词匹配进行文档检索，适用于简单场景。
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

#### 构造参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `documents` | `dict[str, str]` | - | 文档ID到文档内容的映射 |
| `context_label` | `str` | `"KEYWORD_RETRIEVER"` | 上下文源名称 |

#### 特性

- **关键词匹配**：基于简单的词频统计计算相关性
- **轻量实现**：不需要向量嵌入，计算开销小
- **快速部署**：适用于小型文档集或原型开发

---

## MCP（外部上下文源）

### MCP 类

::: info MCP = 通过可调用函数接入外部上下文
`MCP` 适配器是一个轻量 ContextProvider：你提供一个 callable，返回 items，
MASFactory 会把 items 映射为 `ContextBlock` 注入 `CONTEXT`。
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

#### 使用示例（只演示 Observe 注入）

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
    instructions="你是一个简洁的助手。",
    prompt_template="{query}",
    retrievers=[mcp_provider],
)

_, user_prompt, _ = agent.observe({"query": "What is MCP?"})
print(user_prompt)
```

## 工作流兼容层

`masfactory.compatibility` 包可以把外部工作流文档导入为 MASFactory 图。

::: tip 使用指南
面向任务的使用示例见 [`工作流兼容层`](/zh/guide/compatibility)。
:::

### 导入函数

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

加载 Dify YAML 导出。`kind: app` 文档会按 Dify 运行语义编译；通用 `{nodes, edges}` 文档会编译为透传图。

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

加载已经在 Python 中解析好的 Dify mapping。

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

加载 ChatDev workflow YAML 或 chain 风格配置。设置 `use_placeholder=True` 时会构建只保留拓扑的透传图。

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

加载 Langflow JSON 导出，并把常见聊天流组件编译为可执行的 MASFactory 节点。

### 通用 Loader 参数

| 参数 | 类型 | 描述 |
|------|------|------|
| `source` | `str \| Path \| bytes` | 文件路径、内联文档文本，或 UTF-8 bytes |
| `graph_name` | `str \| None` | 生成图的名称 |
| `options` | Compile options | 各产品对应的运行时选项 |
| `aml_path` | `str \| Path \| bool \| None` | 可选的 AML 导出路径，用于 Visualizer 预览和迁移检查 |
| `graph_design_path` | `str \| Path \| bool \| None` | 可选的旧 Visualizer `graph_design.json` 导出路径 |

`aml_path=True` 会在 `masfactory/compatibility/out/` 下写入自动命名的 `.aml` 文件。`graph_design_path=True` 会写入旧 JSON 预览格式。相对路径会解析到该目录下；绝对路径会直接使用。

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

Dify 的 LLM 节点默认会根据 Dify model 配置解析真实 OpenAI-compatible 模型。离线测试时设置 `use_stub_llm=True`。

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

这些 helper 用于生成 AML 文档，便于 Visualizer 预览、源级检查和迁移工作流。

### Legacy Graph Design Helpers

```python
from masfactory.compatibility import (
    dify_document_to_graph_design,
    chatdev_document_to_graph_design,
    langflow_document_to_graph_design,
    write_graph_design_json,
)
```

这些 helper 可以在不构建可执行图的情况下生成适合 Visualizer 预览的 `{"graph_design": ...}` 文档。它们保留给 legacy 预览工具使用；新工作流优先使用 AML helper。

### Blueprint 层 API

更底层的 blueprint API 主要用于扩展兼容层：

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

`GraphBlueprint` 是导入器使用的标准化中间表示。它包含 `ExternalNode` 和 `ExternalEdge` 记录，随后再被物化为 MASFactory 节点和边。
