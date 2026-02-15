
# 安装 MASFactory

本页目标：用 **PyPI** 一条命令安装 MASFactory，验证安装正确，然后安装 **MASFactory Visualizer**（VS Code 插件）用于预览与调试 Graph。

## 环境要求

- Python：`>= 3.10`
- 推荐：在虚拟环境中安装（`venv` / `conda` / `uv` 均可）

## 1) 从 PyPI 安装 MASFactory

建议先升级 pip：

```bash
python -m pip install -U pip
```

然后安装 MASFactory：

```bash
pip install -U masfactory
```

如果你的网络环境需要指定镜像源，可使用（示例）：

```bash
pip install -U masfactory -i https://pypi.org/simple
```

## 2) 验证安装是否正确

在命令行执行：

```bash
python -c "import masfactory; print('masfactory version:', masfactory.__version__)"
```

进一步验证核心对象可导入：

```bash
python -c "from masfactory import RootGraph, Graph, Loop, Agent, CustomNode; print('import ok')"
```

::: tip 提示
这一步只验证“包安装与导入”是否正常；不需要配置任何模型 API Key。
:::

## 3) 安装 MASFactory Visualizer（VS Code 插件）

MASFactory Visualizer 是 VS Code 扩展，用于：
- 预览 Python/JSON 中的 Graph 结构（Preview/Vibe）
- 运行时追踪（Run/Debug）
- Human-in-the-loop 交互（Chat / File Edit 等）

### 从 VS Code 插件市场安装

1. 打开 VS Code → Extensions（扩展）
2. 搜索：`MASFactory Visualizer`
3. 安装并 Reload


## 4) 验证 Visualizer 是否可用

任意打开一个包含 MASFactory 构图代码的 `.py` 文件，然后：

- 点击活动栏（左侧）**MASFactory Visualizer** 图标打开侧边栏视图，或
- 在命令面板中运行：
  - `MASFactory Visualizer: Start Graph Preview`
  - `MASFactory Visualizer: Open Graph in Editor Tab`

如果能看到 Graph Preview 画布并正常渲染节点与边，说明安装完成。

下一步建议阅读：
- [MASFactory Visualizer](/zh/start/visualizer)
- [开发指南 · MASFactory Visualizer](/zh/guide/visualizer)
