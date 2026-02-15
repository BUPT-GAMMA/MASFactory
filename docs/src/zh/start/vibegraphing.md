# VibeGraphing 入门

`VibeGraphing` 是 MASFactory 面向“意图驱动编排”场景提供的一套工作流构建方式：你可以先用自然语言向 AI 描述目标与约束，再基于生成的图结构设计进行可视化预览与迭代收敛。

- 首先用自然语言描述要实现的系统形态（目标、阶段、约束、输入输出等）；
- 系统根据用户需求进行需求分析、结构生成与角色生成，并在每个阶段允许用户交互；
- 产出一个可读、可编辑、可编译为可运行工作流的结构设计工件；

<ThemedDiagram
  light="/imgs/tutorial/chatdev-lite/prog-vibe-pipeline-light.svg"
  dark="/imgs/tutorial/chatdev-lite/prog-vibe-pipeline-dark.svg"
  alt="VibeGraphing：意图 → graph_design → 编译 → 运行"
/>
---

## 最小示例：从意图生成一个可运行工作流

```python
import os
from pathlib import Path

from masfactory import RootGraph, VibeGraph, NodeTemplate, OpenAIModel

model = OpenAIModel(
    model_name=os.getenv("MODEL", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
)

Workflow = NodeTemplate(
    VibeGraph,
    invoke_model=model,
    build_model=model,
    build_instructions="Build a simple linear workflow: ENTRY -> a -> b -> EXIT.",
    build_cache_path=Path("assets/cache/graph_design.json"),
)

g = RootGraph(
    name="vibegraphing_quickstart",
    nodes=[("workflow", Workflow)],
    edges=[
        ("ENTRY", "workflow", {}),
        ("workflow", "EXIT", {}),
    ],
)

g.build()
g.invoke({})
```

---

## 如何迭代设计

当 `build_cache_path` 文件存在时，后续运行会直接读取缓存并编译执行。  
你可以：

- 手工编辑 `assets/cache/graph_design.json`（或用 **MASFactory Visualizer** 在 Vibe 视图编辑）；
- 再次运行代码，观察结构变化与运行效果；
- 想“重新生成设计”时，删除缓存文件再运行即可。
