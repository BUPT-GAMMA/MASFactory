# Install MASFactory

This page installs MASFactory from **PyPI**, verifies the installation, and then installs **MASFactory Visualizer** (VS Code extension) for graph preview and debugging.

## Requirements

- Python: `>= 3.10`
- Recommended: install in a virtual environment (`venv` / `conda` / `uv`)

## 1) Install MASFactory from PyPI

Upgrade `pip` first:

```bash
python -m pip install -U pip
```

Install MASFactory:

```bash
pip install -U masfactory
```

If you need to specify an index URL (example):

```bash
pip install -U masfactory -i https://pypi.org/simple
```

## 2) Verify the installation

Check the installed version:

```bash
python -c "import masfactory; print('masfactory version:', masfactory.__version__)"
```

Verify key imports:

```bash
python -c "from masfactory import RootGraph, Graph, Loop, Agent, CustomNode; print('import ok')"
```

::: tip Note
This only verifies that the package is installed and importable. You do not need any model API keys for this step.
:::

## 3) Install MASFactory Visualizer (VS Code extension)

MASFactory Visualizer is a VS Code extension for:

- previewing graph topology from Python/JSON (Preview / Vibe)
- runtime tracing (Run / Debug)
- human-in-the-loop interactions (Chat / File Edit, etc.)

### Install from VS Code Marketplace

1. Open VS Code → **Extensions**
2. Search for: `MASFactory Visualizer`
3. Install and reload

## 4) Verify Visualizer works

Open any `.py` file that builds a MASFactory graph, then:

- click **MASFactory Visualizer** in the Activity Bar to open the sidebar view, or
- run in Command Palette:
  - `MASFactory Visualizer: Start Graph Preview`
  - `MASFactory Visualizer: Open Graph in Editor Tab`

If you can see the Graph Preview canvas and nodes/edges render correctly, the installation is complete.

Next:

- [MASFactory Visualizer](/start/visualizer)
- [Dev Guide · MASFactory Visualizer](/guide/visualizer)
