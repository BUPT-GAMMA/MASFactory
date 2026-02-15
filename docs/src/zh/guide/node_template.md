# NodeTemplate（模板、作用域与依赖生命周期）

`NodeTemplate` 是 MASFactory 在“声明式装配”中用于**复用节点配置**的核心机制。它将一个节点（例如 `Agent`、`Loop`、`Switch`、子图等）的构造参数固化为可复用的模板，并在装配阶段由 Graph 统一物化（materialize）为真实节点实例。

本页将说明：

- `NodeTemplate` 的定位与推荐用法；
- 如何用 `Shared` / `Factory` 管理依赖生命周期；
- 4 个 `template_*` 作用域函数的语义、优先级与典型场景。

---

## 1) NodeTemplate 是什么

`NodeTemplate(NodeCls, **kwargs)` 不是“节点实例”，而是“节点配置模板”。它具有两项关键特征：

1. **可复用**：同一个模板可在不同 Graph、不同子图、不同节点上重复使用；
2. **可克隆**：你可以在模板基础上覆写少量差异参数，生成新的模板。

在声明式构图中，常见写法如下：

```python
from masfactory import RootGraph, Agent, OpenAIModel, NodeTemplate

model = OpenAIModel(model_name="gpt-4o-mini", api_key="...", base_url="...")

BaseAgent = NodeTemplate(Agent, model=model)  # 创建一个节点模板

AssistantAgent = BaseAgent(instructions="你是 Assistant。", prompt_template="输入：{x}")  # 基于模板创建一个新的节点模板
InstructorAgent = BaseAgent(instructions="你是 Instructor。", prompt_template="输入：{x}\n草案：{draft}")  

g = RootGraph(
    name="demo",
    nodes=[
        ("assistant", AssistantAgent),
        ("instructor", InstructorAgent),
    ],
    edges=[
        ("entry", "assistant", {"x": "输入"}),
        ("assistant", "instructor", {"x": "输入", "draft": "草案"}),
        ("instructor", "exit", {"plan": "最终计划"}),
    ],
)

g.build()
```

### 约束

- `NodeTemplate(...)` **不会**直接创建节点实例；
- 节点名由 Graph 在装配期决定：
  - 声明式：`nodes=[("name", template), ...]`
  - 命令式：`g.create_node(template, name="...")`
- `NodeTemplate(...)` 不接受位置参数，也不接受 `name=`（节点名不是模板的一部分）。

---

## 2) Shared / Factory：依赖生命周期控制

`NodeTemplate` 的默认行为是“安全复制”配置，避免多个节点实例意外共享同一份可变对象（例如 `dict/list/set`）。  
当你需要在模板中注入运行时资源时，应显式声明生命周期：

- `Shared(obj)`：强制共享同一个实例（适合无状态或线程安全的资源）
- `Factory(lambda: ...)`：每次物化节点时生成一个新对象（适合需要隔离的有状态资源）

### 示例：共享 model，隔离 memory

```python
from masfactory import Agent, NodeTemplate, OpenAIModel
from masfactory.core.node_template import Shared, Factory
from masfactory.adapters.memory import HistoryMemory

model = OpenAIModel(model_name="gpt-4o-mini", api_key="...", base_url="...")

BaseAgent = NodeTemplate(
    Agent,
    model=Shared(model),
    # 每个 Agent 节点拥有独立的对话历史
    memories=[Factory(lambda: HistoryMemory(top_k=100, memory_size=10000))],
)
```

> 备注：部分内置类型（例如 `Model`）已在类上标注 `__node_template_scope__ = "shared"`，可被模板直接复用；  
> 但对非框架内对象，建议优先使用 `Shared/Factory` 使生命周期显式化。

---

## 3) template_*：装配期的“默认值/覆写”作用域

当你需要在“模板已写好”的前提下，**集中**注入/覆写一批节点的参数（尤其是嵌套子图内部节点）时，可以使用 4 个 `template_*` 作用域函数（均为 context manager）：

- `template_defaults(**kwargs)`：全局“填空”默认值（仅当模板未显式提供该参数时才生效）。
- `template_overrides(**kwargs)`：全局“强制覆写”（无论模板是否显式提供都会覆盖）。
- `template_defaults_for(selector..., **kwargs)`：对匹配模板“填空”默认值（按 name/type 选择）。
- `template_overrides_for(selector..., **kwargs)`：对匹配模板“强制覆写”（按 name/type 选择）。

它们只对 **NodeTemplate 的物化过程**生效，因此应包裹发生物化的代码：
 `g.build()`

---

## 4) selector 语义与限制（必须理解）

`template_defaults_for / template_overrides_for` 选择的是 **NodeTemplate 的声明**（declaration），而不是运行时对象实例。  
它们的匹配由两部分组成：

- `selector`：匹配声明的 **节点名（name）** 与 **节点类型（class）**；
- `path_filter`（可选）：进一步按“创建路径”做范围过滤，用来区分同名的嵌套节点。

### selector：只匹配声明信息（name + class）

selector 的关键点是：它只基于“声明信息”匹配，而不依赖运行时实例。

- `type_filter` 使用 `issubclass` 语义；
- `name_filter` 默认是精确匹配（大小写敏感）；需要更复杂规则时可传 callable 或正则对象；
- `predicate` 接收 `SelectionTarget(name, cls, obj=None)`；在 NodeTemplate 场景下 `obj` 恒为 `None`（因为尚未物化实例）。

### path_filter：用创建路径区分同名嵌套节点

`path_filter` 用于匹配“创建路径”：

`root_graph > ... > owner_graph > node_name`

语法为：`segment > segment > ...`，其中 `segment` 可以是：

- 具体名字（只能包含字母/数字/`_`/`-`）
- `*`：匹配 1 个路径段
- `**`：匹配 0～多个路径段

匹配默认是“可在路径任意位置命中”（内部会隐式在头尾加 `**`），因此通常只需写最有辨识度的片段即可。  
例如：

- 覆写所有 Phase 内部名为 `instructor` 的 Agent：`name_filter="instructor"`
- 只覆写 `demand_analysis` 这个 Phase 内部的 `instructor`：`path_filter="demand_analysis>instructor"`

---

## 5) 优先级（从低到高）

装配期的应用顺序可以概括为（从低到高）：

1. `template_defaults_for(...)`（对匹配模板填空，后进入的作用域优先）
2. `template_defaults(...)`（全局填空）
3. `template_overrides(...)`（全局强制覆写）
4. `template_overrides_for(...)`（对匹配模板强制覆写）

“填空（defaults）”与“覆写（overrides）”的关键差异在于：  
defaults 只在字段缺失时生效；overrides 总是覆盖。

---

## 6) 典型用法：覆写子图内部节点（跨层级复用）

下面示例展示两种常见场景：

1. 不改 Phase 模板代码，统一增强所有 `instructor` 的指令；
2. 不改节点命名，通过 `path_filter` 只覆写某个 Phase 内部的 `instructor`；
3. 按 Phase 节点名覆写某一个 Phase 的 `phase_instructions`。

```python
from masfactory import RootGraph, Loop, Agent, NodeTemplate
from masfactory.core.node_template import template_defaults_for, template_overrides_for

Phase = NodeTemplate(
    Loop,
    nodes=[
        ("assistant", NodeTemplate(Agent)),
        ("instructor", NodeTemplate(Agent)),
    ],
    edges=[
        ("controller", "assistant", {"workspace": ""}),
        ("assistant", "instructor", {"workspace": ""}),
        ("instructor", "controller", {"workspace": ""}),
    ],
)

g = RootGraph(
    name="demo",
    nodes=[
        ("demand_analysis", Phase),
        ("coding", Phase),
    ],
    edges=[
        ("entry", "demand_analysis", {"workspace": ""}),
        ("demand_analysis", "coding", {"workspace": ""}),
        ("coding", "exit", {"workspace": ""}),
    ],
)

with (
    # 对所有 Agent 填充缺省开关（模板未显式设置时生效）
    template_defaults_for(type_filter=Agent, hide_unused_fields=True),
    # 例 1：对所有名为 instructor 的 Agent 强制覆写指令（覆盖子图内部同名节点）
    template_overrides_for(
        type_filter=Agent,
        name_filter="instructor",
        instructions="你是 Instructor。请以严格标准审阅并补齐关键风险与约束。",
    ),
    # 例 2：只覆写 demand_analysis 这个 Phase 内部的 instructor（无需改内部节点名）
    template_overrides_for(
        type_filter=Agent,
        name_filter="instructor",
        path_filter="demand_analysis>instructor",
        instructions="你是 Instructor。请以更严格的标准审阅，并给出可验证的验收标准与风险清单。",
    ),
    # 例 3：对名为 demand_analysis 的 Phase（Loop 节点）覆写 attributes
    template_overrides_for(
        type_filter=Loop,
        name_filter="demand_analysis",
        attributes={"phase_instructions": "Demand analysis：明确目标与约束。"},
    ),
):
    g.build()
```

---

## 7) 与“命令式构图”的关系

`template_*` 仅作用于 **NodeTemplate 的物化**。因此：

- 你若使用 `g.create_node(Agent, ...)`（直接传类），`template_*` 不会生效；
- 你若使用 `g.create_node(BaseAgentTemplate, name="...")`（传模板），`template_*` 会在该次创建时生效；
- 声明式构图通常在 `build()` 集中物化，更适合利用 `template_*` 做“集中覆写”。
