# VibeGraphing

本页给出一个更完整的 `VibeGraph` 示例：生成 `graph_design.json`、缓存、再编译运行。

<ThemedDiagram
  light="/imgs/tutorial/chatdev-lite/prog-vibe-pipeline-light.svg"
  dark="/imgs/tutorial/chatdev-lite/prog-vibe-pipeline-dark.svg"
  alt="VibeGraphing：意图 → graph_design → 编译 → 运行"
/>

---

## 示例：生成一个线性工作流并运行

```python
import os
from pathlib import Path

from masfactory import RootGraph, VibeGraph, NodeTemplate, OpenAIModel

model = OpenAIModel(
    model_name=os.getenv("MODEL", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
)

build_instructions = """
Build a linear workflow with 3 Agents
"""

Workflow = NodeTemplate(
    VibeGraph,
    invoke_model=model,
    build_model=model,
    build_instructions=build_instructions,
    build_cache_path=Path("assets/cache/example_graph_design.json"),
)

g = RootGraph(
    name="vibegraph_example",
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

## 迭代建议

- 第一次运行后检查 `assets/cache/example_graph_design.json`
- 用 Visualizer 在 Vibe 视图预览/编辑结构
- 修改保存后再次运行，验证编译与运行结果

