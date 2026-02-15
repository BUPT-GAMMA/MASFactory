# 声明式 vs 命令式：两种开发范式

MASFactory 支持两种开发范式：

- **声明式（Declarative）**：在创建 `RootGraph/Graph/Loop` 时**一次性声明**拓扑结构；在 `build()` 阶段框架会根据这些声明**装配出**节点与边并完成一致性检查。  
- **命令式（Imperative）**：先创建 `Graph/RootGraph/Loop` 对象，然后**逐条调用** `create_node()` / `create_edge()`把节点和边添加到图上；这种写法很像给 Graph 下达一系列构建命令，因此称为“命令式”。  

::: tip 选择建议
- 如果你要搭建的工作流是**静态的**，使用声明式更加直观便捷。
- 如果你要搭建的工作流会依据超参数运行时决定部分结构，使用命令式功能更加强大。
:::

---

## 1) 同一个工作流的两种写法
让我们回到 [第一行代码](/zh/start/the_first_code) 中的例子，我们使用两种开发方式实现它：

以下两段代码在运行时行为上等价，差别主要体现在“构图阶段”的组织方式与表达形式。

`entry -> analyze -> answer -> exit`

### 声明式

```python
from masfactory import RootGraph, Agent, OpenAIModel, NodeTemplate

# 1) 创建模型配置（建议在真实项目中从环境变量/配置文件读取）
model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_API_URL",
    model_name="gpt-4o-mini",
)

# 2) 声明一个可复用的节点模板（用于批量创建同构 Agent 节点）
BaseAgent = NodeTemplate(Agent, model=model)

# 3) 声明式构图：在初始化阶段一次性声明 nodes / edges；build() 时由框架装配结构并做一致性校验
g = RootGraph(
    name="qa_two_stage_decl",
    nodes=[
        # 复用模板：仅覆盖 instructions / prompt_template 等少量差异参数
        ("analyze", BaseAgent(instructions="你是问题分析专家。", prompt_template="用户问题：{query}")),
        # 单节点内联模板：适用于一次性节点（不需要单独抽出 BaseAgent）
        (
            "answer",
            NodeTemplate(
                Agent,
                model=model,
                instructions="你是解决方案专家，基于分析给出最终回答。",
                prompt_template="问题：{query}\n分析：{analysis}",
            ),
        ),
    ],
    edges=[
        ("entry", "analyze", {"query": "用户问题"}),
        ("analyze", "answer", {"query": "原始问题", "analysis": "分析结果"}),
        ("answer", "exit", {"answer": "最终回答"}),
    ],
)

g.build()
out, _attrs = g.invoke({"query": "我想学习 Python，但不知道从哪里开始"})
print(out["answer"])
```
### 命令式

```python
from masfactory import RootGraph, Agent, OpenAIModel, NodeTemplate

# 1) 创建模型配置
model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",        # OpenAI 官方可填 "https://api.openai.com/v1"
    model_name="gpt-4o-mini",
)

# 2) 命令式构图：先创建图对象，再逐条创建节点与边
g = RootGraph(name="qa_two_stage_imp")

BaseAgent = NodeTemplate(Agent, model=model)  # 命令式里也可以用 NodeTemplate 复用配置

# 逐条创建节点（create_node）
analyze = g.create_node(BaseAgent, name="analyze", instructions="你是问题分析专家。", prompt_template="用户问题：{query}")
answer = g.create_node(
    Agent,  # 不使用 NodeTemplate 的写法
    name="answer",
    instructions="你是解决方案专家，基于分析给出最终回答。",
    model=model,
    prompt_template="问题：{query}\n分析：{analysis}",
)

# 逐条创建边（edge_from_entry / create_edge / edge_to_exit）
g.edge_from_entry(analyze, {"query": "用户问题"})
g.create_edge(analyze, answer, {"query": "原始问题", "analysis": "分析结果"})
g.edge_to_exit(answer, {"answer": "最终回答"})

g.build()
out, _attrs = g.invoke({"query": "我想学习 Python，但不知道从哪里开始"})
print(out["answer"])
```


---

## 2) 进阶：什么时候选哪种？怎么写更稳？

本页仅提供入门级对照示例。更系统的取舍原则、最佳实践与常见问题请参见：

- [命令式 vs 声明式（进阶）](/zh/guide/declarative_vs_imperative_advanced)
