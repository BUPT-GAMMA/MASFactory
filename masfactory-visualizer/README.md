# MASFactory Visualizer

MASFactory Visualizer is a VS Code extension for **visualizing, editing, and debugging** MASFactory workflows directly in VS Code.

It provides a real-time graph view for Python workflow code and supports run/debug session tracking plus human-in-the-loop interactions.

## Highlights

- **Preview MASFactory graphs** from Python (`.py`) files.
- **Vibe mode** to preview and edit `.aml` workflow documents, with legacy `graph_design*.json` preview support.
- **AML source preview** with syntax highlighting in the VS Code editor.
- **Run/Debug session view** to inspect execution state, node details, and edge transitions.
- **Human-in-the-loop popup** with per-session conversation history.
- **Editor title action** for quickly opening the graph in an editor tab.
- **Custom graph colors** via extension settings.

## Quick Start

1. Install the extension (`.vsix`) in VS Code.
2. Open a MASFactory project folder.
3. Open a MASFactory graph Python file, an AML (`.aml`) file, or a legacy `graph_design*.json` file.
4. Use one of the commands below, or click the **MASFactory Visualizer** icon in the Activity Bar.

## Commands

- `MASFactory Visualizer: Start Graph Preview` (`masfactory-visualizer.start`)
- `MASFactory Visualizer: Open Graph in Editor Tab` (`masfactory-visualizer.openInEditor`)

## Tips

- If you are running a MASFactory workflow with Visualizer integration enabled, Visualizer can automatically show run/debug sessions and human requests.
- If you do not see updates, reopen the editor tab or run the command again.
