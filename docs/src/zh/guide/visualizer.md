# MASFactory Visualizer

本章将介绍 **MASFactory Visualizer** 的使用方法与界面功能。Visualizer 的目标是让你在“结构设计 → 可执行装配 → 运行追踪 → 人在回路”的全过程中，都能以统一的图视图进行验证与定位问题。

---

## 打开方式

Visualizer 支持两种打开方式；二者共享同一套解析与运行时数据源，功能等价但使用体验略有差异。

### 方式 A：侧边栏视图（Activity Bar）

点击 VS Code 左侧活动栏的 **MASFactory Visualizer** 图标，即可打开 **Graph Preview** 侧边栏视图。

优点：
- 适合“边写代码、边看图”的工作方式；
- 与编辑器并排，不占用额外标签页。

![side-bar](/imgs/visualizer/side-bar.png)

### 方式 B：编辑器标签页（Webview Panel）

通过命令面板打开：
- `MASFactory Visualizer: Start Graph Preview`
- `MASFactory Visualizer: Open Graph in Editor Tab`
或者在 `.py`文件或`.json`文件的Editor Tab中点击右上角功能按钮：
![editor-button](/imgs/visualizer/editor-button.png)

优点：
- 更大的画布空间，适合复杂拓扑与运行时追踪；
- 可与代码标签页并列管理，便于在不同工作区中切换。

![overview](/imgs/visualizer/overview.png)

---

## 页面布局

Visualizer 的整体布局可以概括为四个区域：

1) **顶部栏（图中 1）**：包含版本/标题、选项卡（Preview / Debug / Run / Vibe）、以及全局入口（如 Chat 按钮及其角标提示）。
3) **主画布（图中 2）**：节点与边的拓扑渲染区域，支持缩放、拖拽、Fit/Relayout 等交互操作。

在 **Run / Debug** 选项卡中，主画布下方还会额外出现 **底部信息栏**，用于按类别查看运行过程的细节（Node / Logs / Messages / Human / System / Graph Structure）。


![overview](/imgs/visualizer/overview-tag.png)

---

## 选项卡

### 1) Preview：在开发阶段的图结构预览

**适用场景**
- 用于在开发阶段预览 `.py` 文件中的 Graph/NodeTemplate 构图结果；
- 验证子图嵌套、Loop/Switch 等控制结构是否符合预期；
- 在运行之前做“结构一致性检查”（是否遗漏 ENTRY/EXIT、是否存在孤立节点等）；

**主要功能**
- 基于 Python 解析器提取图结构，并渲染为拓扑视图；
- 双击节点可以快速将光标定位到对应的 Python 代码所在行；
- 支持视图操作：Fit、Relayout、缩放、拖拽等。

![preview-tab](/imgs/visualizer/preview-tab.png)

### 2) Debug：调试追踪

**适用场景**
- 在 VS Code Debug 会话中运行 MASFactory 程序；
- 结合断点、异常与节点运行轨迹进行定位；
- 观察“执行到哪里了”“哪里提前退出了”“哪里被条件分支跳过了”等问题。

**主要功能**
- 接收调试会话事件（断点/异常/进程等）并在 UI 中展示；
- 在图上标注当前执行位置与历史执行轨迹（按运行状态着色/标记）；

![debug](/imgs/visualizer/debug.png)

**页面布局**
- *会话列表（左侧）*：按调试会话维度组织数据；可在多个会话之间快速切换。
- *状态栏（上方）*：展示断点/异常等关键信息，并提供“打开位置”等定位入口。
- *拓扑画布（中间）*：以图形式标注当前执行位置与已执行轨迹，辅助定位执行路径问题。
- *底部信息栏（下方）*：用于查看节点详情、日志、消息与系统事件。


### 3) Run：运行追踪

**适用场景**
- 直接运行脚本/应用（非 Debug 模式）；
- 需要观察运行时的消息流转、节点状态、阶段推进；
- 同时处理 Human-in-the-loop 交互请求。

**主要功能**
- 按进程/会话（session）维度管理运行记录；
- 展示节点状态、消息事件与系统日志；
- 接收 Human 请求并在 UI 中提供回复入口。

![run-tab](/imgs/visualizer/run-tab.png)

**页面布局**
- *会话列表（左侧）*：按进程/会话维度管理运行记录；已退出的会话会保留在列表中，便于回溯，并提供删除入口由用户自行清理。
- *状态栏（上方）*：展示模式（Run）、PID、最后活跃时间、节点/边数量与运行状态等信息。
- *拓扑画布（中间）*：渲染运行时图结构，并按状态对节点进行标注（例如已执行、正在执行、等待等）。
- *底部信息栏（下方）*：按类别查看运行细节（节点、日志、消息、人机交互请求、系统事件与结构快照等）。


### 4) Vibe：graph_design 预览与编辑

**适用场景**
- 使用 VibeGraphing 生成 `graph_design.json` 后进行人工校对与收敛；
- 在进入“完整字段生成阶段”前，对结构设计进行快速调整；
- 将结构迭代沉淀为可版本化的中间表示（IR）。

**主要功能**
- 读取并渲染 `graph_design.json`（标准以仓库 `graph_design/` 目录为准）；
- 支持在可视化界面中编辑结构并保存（用于后续编译/运行验证）。

![vibe-tab](/imgs/visualizer/vibe-tab.png)

**页面布局**
- *组件面板（左侧）*：提供常用组件入口（Agent / Graph / Loop / Switch …），支持拖拽到画布以新增节点。
- *编辑画布（中间）*：展示并编辑 `graph_design.json` 的拓扑结构；支持 Fit / Relayout、缩放、拖拽、右键菜单等操作。
- *详情面板（右侧）*：展示并编辑选中节点/边的属性（如类型、标签、agent、tools、attributes 等），并可保存回 JSON 文件。

---

## Human-in-the-loop：对话与文件预览/编辑

当工作流运行中触发 Human 交互节点时，Visualizer 会接收来自进程的交互请求并提示用户处理。典型交互包括：

- **对话输入**：以会话为单位归档消息（Agent ↔ Human），并将用户回复回传给运行中的工作流；
- **文件预览/编辑**：将指定文件在 VS Code 中打开，并在 Visualizer 中提供对应的预览视图（例如在 Vibe 视图编辑 `graph_design.json`）。

![human](/imgs/visualizer/human.png)
