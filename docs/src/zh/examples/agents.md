# Agents（SingleAgent / Agent / DynamicAgent）

MASFactory 里常见的三种 Agent 形态：

- `SingleAgent`：**不进图**，直接 `invoke(dict)`，适合脚本/快速验证
- `Agent`：**图内节点**，用边定义输入/输出字段，是工作流的主力
- `DynamicAgent`：**图内节点**，每次执行前从输入里读取新 `instructions`（动态换角色/策略）

## 消息传递视角

- **水平（Edge keys）**：Agent 通过边字段接收上下文并输出结构化字段
- **垂直（attributes）**：可显式开启 `pull_keys/push_keys` 让 Agent 读写图级状态（默认 Agent 不继承）

## 示意图
![示意图](/imgs/examples/agent.png)

---

## 1) SingleAgent：独立调用（不需要 Graph）

```python
from masfactory import OpenAIModel, SingleAgent

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

agent = SingleAgent(
    name="demo_single",
    model=model,
    instructions="你是一个简洁的助手，请用 JSON 回复：{answer: ...}",
    prompt_template="问题：{query}",
)

result = agent.invoke({"query": "一句话解释什么是 DAG？"})
print(result)  # dict（由输出 formatter 解析得到）
```

::: warning 注意
`SingleAgent` 不能被嵌入到 `Graph/RootGraph` 中（只用于独立调用）。图内请使用 `Agent`。
:::

---

## 2) Agent：作为图节点（推荐）

### 2A) 声明式（主推）

```python
from masfactory import Agent, NodeTemplate, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

BaseAgent = NodeTemplate(Agent, model=model)

g = RootGraph(
    name="agent_in_graph",
    nodes=[
        ("writer", BaseAgent(instructions="你是写作者。", prompt_template="主题：{topic}")),
        ("critic", BaseAgent(instructions="你是审稿人。", prompt_template="草稿：{draft}")),
    ],
    edges=[
        ("entry", "writer", {"topic": "主题"}),
        ("writer", "critic", {"draft": "草稿正文"}),
        ("critic", "exit", {"review": "审稿意见"}),
    ],
)

g.build()
out, _attrs = g.invoke({"topic": "用 3 条要点解释 MASFactory 的价值"})
print(out["review"])
```

### 2B) 命令式（备选）

```python
from masfactory import Agent, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

g = RootGraph(name="agent_in_graph")

writer = g.create_node(
    Agent,
    name="writer",
    model=model,
    instructions="你是写作者。",
    prompt_template="主题：{topic}",
)
critic = g.create_node(
    Agent,
    name="critic",
    model=model,
    instructions="你是审稿人。",
    prompt_template="草稿：{draft}",
)

g.edge_from_entry(writer, {"topic": "主题"})
g.create_edge(writer, critic, {"draft": "草稿正文"})
g.edge_to_exit(critic, {"review": "审稿意见"})

g.build()
out, _attrs = g.invoke({"topic": "用 3 条要点解释 MASFactory 的价值"})
print(out["review"])
```

::: tip 调试小技巧
你可以读 `agent.last_prompt` 查看最近一次 system/user prompt（便于排查字段缺失、格式不对等问题）。
:::

---

## 3) DynamicAgent：运行时动态换指令

场景：上游节点先判断“用户想要什么类型的服务”，再把对应的 `instructions` 传给同一个 `DynamicAgent`。

### 3A) 声明式（主推）

```python
from masfactory import CustomNode, DynamicAgent, NodeTemplate, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)


def choose_role(d: dict) -> dict:
    q = str(d.get("query", ""))
    if "退款" in q or "投诉" in q:
        ins = "你是客服经理，负责投诉/退款，态度专业且克制。"
    elif "价格" in q or "套餐" in q:
        ins = "你是产品顾问，回答功能/版本/价格。"
    else:
        ins = "你是技术支持工程师，负责排查报错与部署问题。"
    return {"instructions": ins, "query": q}


Dynamic = NodeTemplate(
    DynamicAgent,
    model=model,
    default_instructions="你是一个通用助手。",
    instruction_key="instructions",
    prompt_template="{query}",
)

g = RootGraph(
    name="dynamic_agent_demo",
    nodes=[
        ("role_selector", CustomNode, choose_role),
        ("service", Dynamic),
    ],
    edges=[
        ("entry", "role_selector", {"query": "用户咨询"}),
        ("role_selector", "service", {"instructions": "本次角色指令", "query": "用户咨询"}),
        ("service", "exit", {"response": "回复"}),
    ],
)

g.build()
out, _attrs = g.invoke({"query": "我对服务不满意，要求退款"})
print(out["response"])
```

### 3B) 命令式（备选）

```python
from masfactory import CustomNode, DynamicAgent, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)


def choose_role(d: dict) -> dict:
    q = str(d.get("query", ""))
    if "退款" in q or "投诉" in q:
        ins = "你是客服经理，负责投诉/退款，态度专业且克制。"
    elif "价格" in q or "套餐" in q:
        ins = "你是产品顾问，回答功能/版本/价格。"
    else:
        ins = "你是技术支持工程师，负责排查报错与部署问题。"
    return {"instructions": ins, "query": q}


g = RootGraph(name="dynamic_agent_demo")

role_selector = g.create_node(CustomNode, name="role_selector", forward=choose_role)
service = g.create_node(
    DynamicAgent,
    name="service",
    model=model,
    default_instructions="你是一个通用助手。",
    instruction_key="instructions",
    prompt_template="{query}",
)

g.edge_from_entry(role_selector, {"query": "用户咨询"})
g.create_edge(role_selector, service, {"instructions": "本次角色指令", "query": "用户咨询"})
g.edge_to_exit(service, {"response": "回复"})

g.build()
out, _attrs = g.invoke({"query": "我对服务不满意，要求退款"})
print(out["response"])
```
