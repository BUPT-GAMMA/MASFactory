# API Reference

本文档提供了 MASFactory 框架的完整 API 参考，包括所有核心类、方法和接口的详细说明。

::: tip 使用指南
- 点击左侧导航栏快速定位到相应模块
- 每个类都包含了详细的构造参数说明和使用示例
- 方法参数和返回值都有完整的类型注解
- 使用 <kbd>Ctrl</kbd> + <kbd>F</kbd> 快速搜索特定 API
:::

::: info 版本信息
当前文档对应 MASFactory v1.0.0
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

---

### Message 类

::: info 消息基类
Message 是所有消息的抽象基类，提供消息内容的统一接口。
:::

```python
class Message(ABC):
    def __init__(self)
```

#### 核心方法

##### __add__()

```python
def __add__(self, other: Message) -> Message
```

连接两个消息对象。

**参数：**
- `other`: 要连接的另一个消息

**返回：**
- `Message`: 连接后的消息

##### content()

```python
def content() -> str
```

获取消息的字符串表示。

**返回：**
- `str`: 消息内容

##### dict()

```python
def dict() -> dict
```

获取消息的内部字典对象。

**返回：**
- `dict`: 消息的字典表示

::: warning 注意
修改返回的字典对象会影响消息内容。
:::

---

### JsonMessage 类

::: info JSON 格式消息
JsonMessage 是 JSON 格式的消息实现，继承自 Message 类。
:::

```python
class JsonMessage(Message):
    def __init__(self, content: dict)
```

#### 构造参数

| 参数 | 类型 | 描述 |
|------|------|------|
| `content` | `dict` | 消息的内容，表示为 Python 字典 |

#### 特殊方法

##### __add__()

```python
def __add__(self, other: Message) -> JsonMessage
```

合并两个消息的内容。

**合并规则：**
- 如果有重复键，other 中的值会覆盖当前消息中的值
- 返回类型保持为 JsonMessage

**示例：**
```python
msg1 = JsonMessage({"x": 1, "z": 4})
msg2 = JsonMessage({"x": 2, "y": 3})
result = msg1 + msg2
# 结果: {"x": 2, "y": 3, "z": 4}
```

---

### MessageFormatter 类

::: info 消息格式化器基类
MessageFormatter 是所有消息格式化器的抽象基类，实现单例模式。
:::

```python
class MessageFormatter(ABC):
    def __init__(self)
```

#### 核心方法

##### format() *[抽象方法]*

```python
@abstractmethod
def format(self, message: str, key_description: dict) -> Message
```

将原始消息字符串格式化为特定的消息对象。

**参数：**
- `message`: 原始消息字符串
- `key_description`: 描述消息结构的字典

**返回：**
- `Message`: 格式化后的消息对象

**异常：**
- `NotImplementedError`: 子类必须实现此方法

---

### JsonMessageFormatter 类

::: info JSON 消息格式化器
JsonMessageFormatter 是 JSON 格式的消息格式化器，用于将 JSON 字符串转换为 JsonMessage 对象。
:::

```python
class JsonMessageFormatter(MessageFormatter):
    def __init__(self)
```

#### 核心方法

##### format()

```python
def format(self, message: str, key_description: dict) -> JsonMessage
```

解析 JSON 字符串并验证其结构是否符合要求。

**参数：**
- `message`: JSON 字符串消息
- `key_description`: 描述消息结构的字典

**返回：**
- `JsonMessage`: 包含验证数据的 JsonMessage 对象

**异常：**
- `KeyError`: 如果缺少必需的键
- `json.JSONDecodeError`: 如果消息不是有效的 JSON 格式

**特性：**
- 支持提取 ```json 代码块中的 JSON 内容
- 仅提取 key_description 中存在的字段
- 对缺失的必需字段进行验证

##### format_to_json()

```python
def format_to_json(self, message: str) -> dict
```

将消息字符串转换为 JSON 字典。

**参数：**
- `message`: 原始字符串，支持包含 ```json 代码块的文本

**返回：**
- `dict`: 解析后的 JSON 对象

**异常：**
- `json.JSONDecodeError`: 当字符串不是有效 JSON 时抛出

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
        pull_keys: dict[str, dict|str] | None = {},
        push_keys: dict[str, dict|str] | None = {},
        model_settings: dict | None = None,
        role_name: str | None = None,
        attributes: dict[str, object] | None = None,
        hide_unused_fields: bool = False,
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
| `memories` | `list[Memory] \| None` | `None` | 记忆适配器列表 |
| `retrievers` | `list[Retrieval] \| None` | `None` | 检索适配器列表（RAG/MCP 等） |
| `pull_keys` | `dict[str,dict|str] \| None` | `{}` | 可见/需要的节点变量键及说明 |
| `push_keys` | `dict[str,dict|str] \| None` | `{}` | 执行后写回的节点变量键及说明 |
| `model_settings` | `dict \| None` | `None` | 传递给模型的额外参数 |
| `role_name` | `str` | `None` | Agent 的角色名称 |
| `attributes` | `dict[str,object] \| None` | `None` | Agent 的本地初始节点变量 |
| `hide_unused_fields` | `bool` | `False` | 是否在 prompt 组装中隐藏未使用字段 |

#### 支持的 model_settings 参数

| 参数 | 类型 | 范围 | 描述 |
|------|------|------|------|
| `temperature` | `float` | [0.0, 2.0] | 温度参数，控制输出的随机性 |
| `max_tokens` | `int` | - | 最大输出 token 数 |
| `top_p` | `float` | [0.0, 1.0] | 核采样参数 |
| `stop` | `list[str]` | - | 停止生成的 token 列表 |

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
                role_name: str | None = None)
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
| `memories` | `list[Memory] \| None` | `None` | 记忆模块列表 |
| `retrievers` | `list[Retrieval] \| None` | `None` | 检索适配器列表（RAG/MCP 等） |
| `model_settings` | `dict \| None` | `None` | 模型调用参数 |
| `role_name` | `str \| None` | `None` | 角色名称 |

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
| `default_instructions` | `str` | `""` | 默认指令 |
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

- **动态指令**：可在运行时通过入边消息更新指令
- **灵活配置**：支持自定义指令键名
- **完整功能**：继承 Agent 的所有功能

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
| `description` | `str` | 模型的描述（只读） |

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

::: info OpenAI 模型适配器
OpenAIModel 实现了与 OpenAI API 交互的模型适配器。
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

---

### GeminiModel 类

::: info Google Gemini 模型适配器
GeminiModel 实现了与 Google Gemini API 交互的模型适配器。
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
    def insert(self, key: str, value: str)
    def update(self, key: str, value: str)
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
它不会产出 `ContextBlock`（`get_blocks(...)` 恒为空）。
:::

```python
class HistoryMemory(Memory, HistoryProvider):
    def __init__(self, top_k: int = 10, memory_size: int = 1000, context_label: str = "CONVERSATION_HISTORY")
    def insert(self, role: str, response: str)
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
