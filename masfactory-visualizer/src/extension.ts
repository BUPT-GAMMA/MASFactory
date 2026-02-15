import * as vscode from 'vscode';
import { GraphParser } from './parser/parser';
import { initTreeSitter } from './parser/treeSitter';
import { WebviewProvider } from './webview/webviewProvider';
import { RuntimeHub, type VisualizerUiCommand } from './runtime/runtimeHub';
import { registerDocumentListeners } from './documents/documentTracker';
import { registerPythonDebugAdapterTracking } from './debug/pythonDebugTracker';

/**
 * Extension activation function
 * Called when the extension is activated
 */
export async function activate(context: vscode.ExtensionContext) {
    // Tree-sitter (WASM) is required for Python graph parsing.
    // Do NOT block extension activation on it: if initialization is slow/hangs on a user's machine,
    // VS Code will treat the extension as "activating" forever, and commands/views won't be registered.
    const treeSitterInitPromise = initTreeSitter(context.extensionPath);

    // Runtime bridge (v0.2): WebSocket server + process/session tracking
    const runtimeHub = new RuntimeHub();
    context.subscriptions.push(runtimeHub);

    // Start server on port 0 and inject into terminals via env collection.
    void runtimeHub.start().then(() => {
        const port = runtimeHub.getPort();
        if (port) {
            context.environmentVariableCollection.replace('MASFACTORY_VISUALIZER_PORT', String(port));
        }
    });

    // Inject debug mode into debug sessions via DebugConfigurationProvider.
    // Note: newer Python extension variants may use type "debugpy".
    const pythonDebugTypes = ['python', 'debugpy'];
    for (const debugType of pythonDebugTypes) {
        context.subscriptions.push(
            vscode.debug.registerDebugConfigurationProvider(debugType, {
                resolveDebugConfiguration(_folder, config) {
                    const port = runtimeHub.getPort();
                    const env = { ...(config.env || {}) } as Record<string, string>;
                    if (port) env.MASFACTORY_VISUALIZER_PORT = String(port);
                    env.MASFACTORY_VISUALIZER_MODE = 'debug';
                    return { ...config, env };
                }
            })
        );
    }

    // DebugAdapterTracker: propagate breakpoint/exception events to the webview UI (v0.2 Debug tab).
    registerPythonDebugAdapterTracking({ context, runtimeHub, debugTypes: pythonDebugTypes });

    // Create parser and webview provider
    const parser = new GraphParser();
    const webviewProvider = new WebviewProvider(context, parser, runtimeHub);

    // Visualizer UI commands from Python processes (best-effort UX helpers).
    const onVisualizerUiCommand = (cmd: VisualizerUiCommand) => {
        void webviewProvider.handleVisualizerUiCommand(cmd);
    };
    runtimeHub.on('visualizerUiCommand', onVisualizerUiCommand);
    context.subscriptions.push({
        dispose: () => {
            runtimeHub.off('visualizerUiCommand', onVisualizerUiCommand);
        }
    });

    // Register command: MASFactory Visualizer: Start Graph Preview
    const startCommand = vscode.commands.registerCommand('masfactory-visualizer.start', () => {
        webviewProvider.createOrShowPanel();
    });

    // Register command: MASFactory Visualizer: Open Graph in Editor Tab
    const openInEditorCommand = vscode.commands.registerCommand('masfactory-visualizer.openInEditor', () => {
        webviewProvider.openGraphInEditorTab();
    });

    // Register sidebar view provider
    const sidebarProvider = vscode.window.registerWebviewViewProvider(
        'masfactoryVisualizerView',
        webviewProvider
    );

    // Register webview panel serializer for restoring editor tab after VSCode restart
    const panelSerializer = vscode.window.registerWebviewPanelSerializer('masfactoryVisualizerEditor', {
        async deserializeWebviewPanel(panel: vscode.WebviewPanel, state: any) {
            // Restore the webview panel
            webviewProvider.restoreEditorPanel(panel, state);
        }
    });

    // Subscribe to disposables
    context.subscriptions.push(startCommand, openInEditorCommand, sidebarProvider, panelSerializer);

    // Setup document listeners
    registerDocumentListeners({ context, webviewProvider });

    // Finish Tree-sitter init in background; refresh the active doc once ready.
    void treeSitterInitPromise
        .then(() => {
            const doc = vscode.window.activeTextEditor?.document;
            if (doc?.languageId === 'python') {
                webviewProvider.updateGraph(doc);
            }
        })
        .catch((err) => {
            console.error('[MASFactory Visualizer] Failed to initialize Tree-sitter:', err);
            void vscode.window.showErrorMessage(
                'MASFactory Visualizer: Failed to initialize the Python parser (Tree-sitter). Graph preview may not work.'
            );
        });
}

/**
 * Extension deactivation function
 * Called when the extension is deactivated
 */
export function deactivate() {}
