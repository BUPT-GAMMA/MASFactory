# 并行分支示例

本示例展示如何在MASFactory中实现计划可行性的并行分析工作流，包括：用户需求分析、计划制定、法律和经济可行性的并行评估，以及最终的综合报告生成。

这个工作流展示了一个完整的项目评估流程：

1. **计划师**：根据用户需求制定详细的项目计划
2. **计划分发器**：将制定的计划分发给专业分析师
3. **并行专家分析**：
   - **法律可行性专家**：分析法律合规性和法律风险
   - **经济可行性专家**：分析经济效益和财务可行性
4. **最终报告专家**：整合所有分析结果，生成完整的项目评估报告

## 消息传递视角

- **水平（Edge keys）**：`planner` fan-out 到 `legal_analyst / economic_analyst`，再 fan-in 到 `final_reporter`
- **垂直（attributes）**：本示例未使用，适合补充“全局评估状态/轮次计数”等流程状态

## 示意图
![示意图](/imgs/examples/parallel_branching.png)
## 示例代码（声明式，推荐）
```python
from masfactory import Agent, NodeTemplate, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

BaseAgent = NodeTemplate(Agent, model=model)

graph = RootGraph(
    name="plan_feasibility_workflow",
    nodes=[
        ("planner", BaseAgent(instructions="你是一位专业的项目规划师，负责根据用户需求输出项目计划。", prompt_template="用户需求：{requirement}")),
        ("legal_analyst", BaseAgent(instructions="你是法律可行性分析专家，识别法律合规风险与法律障碍。", prompt_template="用户需求：{requirement}\n项目计划：{plan}")),
        ("economic_analyst", BaseAgent(instructions="你是经济可行性分析专家，评估成本、ROI、现金流与财务风险。", prompt_template="用户需求：{requirement}\n项目计划：{plan}")),
        ("final_reporter", BaseAgent(instructions="你是项目评估总结专家，整合计划、法律分析与经济分析，输出综合报告。", prompt_template=("用户需求：{requirement}\n" "项目计划：{plan}\n" "法律分析：{legal_analysis}\n" "经济分析：{economic_analysis}"))),
    ],
    edges=[
        ("entry", "planner", {"requirement": "用户需求描述"}),
        # fan-out：planner 的输出同时发送到两个分支
        ("planner", "legal_analyst", {"requirement": "用户需求", "plan": "项目计划"}),
        ("planner", "economic_analyst", {"requirement": "用户需求", "plan": "项目计划"}),
        # join：final_reporter 有多个入边，会等待所有打开的入边都收到消息
        ("planner", "final_reporter", {"requirement": "用户需求", "plan": "项目计划"}),
        ("legal_analyst", "final_reporter", {"legal_analysis": "法律可行性分析"}),
        ("economic_analyst", "final_reporter", {"economic_analysis": "经济可行性分析"}),
        ("final_reporter", "exit", {"report": "最终综合报告"}),
    ],
)

graph.build()

# 测试计划可行性分析工作流
sample_requirement = """
我想在城市中心开设一家智能咖啡店，结合人工智能技术提供个性化服务。
店铺面积约200平方米，计划投资150万元，希望通过AI推荐系统、智能点餐、
人脸识别会员系统等技术创新，打造差异化的咖啡体验。
目标是在一年内收回成本，并建立品牌影响力。
"""

out, _attrs = graph.invoke({"requirement": sample_requirement})
print(out["report"])
```

## 示例代码（命令式，备选）

```python
from masfactory import Agent, OpenAIModel, RootGraph

model = OpenAIModel(
    api_key="YOUR_API_KEY",
    base_url="YOUR_BASE_URL",
    model_name="gpt-4o-mini",
)

graph = RootGraph(name="plan_feasibility_workflow")

planner = graph.create_node(
    Agent,
    name="planner",
    model=model,
    instructions="你是一位专业的项目规划师，负责根据用户需求输出项目计划。",
    prompt_template="用户需求：{requirement}",
)
legal_analyst = graph.create_node(
    Agent,
    name="legal_analyst",
    model=model,
    instructions="你是法律可行性分析专家，识别法律合规风险与法律障碍。",
    prompt_template="用户需求：{requirement}\n项目计划：{plan}",
)
economic_analyst = graph.create_node(
    Agent,
    name="economic_analyst",
    model=model,
    instructions="你是经济可行性分析专家，评估成本、ROI、现金流与财务风险。",
    prompt_template="用户需求：{requirement}\n项目计划：{plan}",
)
final_reporter = graph.create_node(
    Agent,
    name="final_reporter",
    model=model,
    instructions="你是项目评估总结专家，整合计划、法律分析与经济分析，输出综合报告。",
    prompt_template=(
        "用户需求：{requirement}\n"
        "项目计划：{plan}\n"
        "法律分析：{legal_analysis}\n"
        "经济分析：{economic_analysis}"
    ),
)

graph.edge_from_entry(planner, {"requirement": "用户需求描述"})

graph.create_edge(planner, legal_analyst, {"requirement": "用户需求", "plan": "项目计划"})
graph.create_edge(planner, economic_analyst, {"requirement": "用户需求", "plan": "项目计划"})

graph.create_edge(planner, final_reporter, {"requirement": "用户需求", "plan": "项目计划"})
graph.create_edge(legal_analyst, final_reporter, {"legal_analysis": "法律可行性分析"})
graph.create_edge(economic_analyst, final_reporter, {"economic_analysis": "经济可行性分析"})

graph.edge_to_exit(final_reporter, {"report": "最终综合报告"})

graph.build()

sample_requirement = """
我想在城市中心开设一家智能咖啡店，结合人工智能技术提供个性化服务。
店铺面积约200平方米，计划投资150万元，希望通过AI推荐系统、智能点餐、
人脸识别会员系统等技术创新，打造差异化的咖啡体验。
目标是在一年内收回成本，并建立品牌影响力。
"""

out, _attrs = graph.invoke({"requirement": sample_requirement})
print(out["report"])
```
