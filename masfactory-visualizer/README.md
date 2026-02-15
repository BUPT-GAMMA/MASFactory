# MASFactory Visualizer

MASFactory Visualizer is a VS Code extension that renders MASFactory graphs in real time, so you can **preview**, **debug/run**, and **iteratively design** multi-agent workflows with a visual graph view.

## Features

- **Preview MASFactory graphs** from Python (`.py`) files.
- **Vibe mode**: preview and edit `graph_design*.json`.
- **Run/Debug sessions**: view sessions, inspect node/edge details, and follow execution states.
- **Human-in-the-loop**: chat requests appear as a popup dialog, with per-session conversation history.

## Quick Start

1. Install the extension (`.vsix`) in VS Code.
2. Open a MASFactory project folder.
3. Open a MASFactory graph Python file (or a `graph_design*.json` file).
4. Run one of the commands below, or click the **MASFactory Visualizer** icon in the Activity Bar.

## Commands

- `MASFactory Visualizer: Start Graph Preview` (`masfactory-visualizer.start`)
- `MASFactory Visualizer: Open Graph in Editor Tab` (`masfactory-visualizer.openInEditor`)

## Tips

- If you are running a MASFactory workflow with Visualizer integration enabled, Visualizer can automatically show run/debug sessions and human requests.
- If you don’t see updates, try reopening the editor tab or re-running the command.

