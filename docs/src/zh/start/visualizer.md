# MASFactory Visualizer

MASFactory Visualizer 是 MASFactory 的 VS Code 可视化工具，用于将「图结构」与「运行时状态」在一个界面中对齐呈现，便于预览、调试与人机交互。

本页定位为“快速入门级”的 Visualizer 说明；更完整的功能细节与使用建议请参考：[开发指南 · MASFactory Visualizer](/zh/guide/visualizer)。

---

## 你可以用它做什么

- **Preview**：预览 Python/JSON 中的 Graph 拓扑（子图、Loop、Switch 等）。
- **Vibe**：预览/编辑 `graph_design.json`（用于 VibeGraphing 生成结构的迭代收敛）。
- **Run / Debug**：运行时追踪节点状态、消息流转与异常信息。
- **Human-in-the-loop**：接收交互请求（对话、文件预览/编辑等），并将用户回复回传给运行中的进程。

---

## 两种打开方式

Visualizer 支持两种打开方式，它们共享同一套解析与运行时数据源：

1) **侧边栏（Activity Bar）**

在 VS Code 左侧活动栏点击 **MASFactory Visualizer** 图标，打开 **Graph Preview** 视图。

![side-bar](/imgs/visualizer/side-bar.png)

2) **编辑器标签页（Webview Panel）**

在命令面板运行：
- `MASFactory Visualizer: Start Graph Preview`（打开/聚焦可视化面板）
- `MASFactory Visualizer: Open Graph in Editor Tab`（在编辑器标签页中打开）
或者在 `.py`文件或`.json`文件的Editor Tab中点击右上角功能按钮：
![editor-button](/imgs/visualizer/editor-button.png)

![overview](/imgs/visualizer/overview.png)
---

## 使用流程

1. 打开一个包含 MASFactory 构图代码的 `.py` 文件；
2. 打开 Visualizer，并切换到 **Preview** 选项卡；
3. 若你在使用 VibeGraphing：生成/更新 `graph_design.json` 后，在 **Vibe** 选项卡预览与编辑；
4. 运行你的工作流后，在 **Run / Debug** 选项卡观察运行轨迹与交互请求。

如果你希望了解每个选项卡的页面布局与完整功能，请继续阅读：[开发指南 · MASFactory Visualizer](/zh/guide/visualizer)。

