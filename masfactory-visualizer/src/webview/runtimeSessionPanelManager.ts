import * as vscode from 'vscode';
import { buildWebviewHtml } from './webviewHtml';
import type { RuntimeHub, RuntimeUiMessage } from '../runtime/runtimeHub';

export type WebviewPostMessage = (target: vscode.Webview, message: unknown) => void;
export type WebviewMessageRegistrar = (webview: vscode.Webview, subscriberId: string) => void;

/**
 * Owns runtime-session specific webview panels and history replay for RuntimeHub events.
 *
 * This keeps WebviewProvider smaller by isolating the runtime-session panel lifecycle and
 * UI warmup ("runtimeWebviewReady") behavior.
 */
export class RuntimeSessionPanelManager {
  private readonly runtimeSessionPanels: Map<string, vscode.WebviewPanel> = new Map();
  private readonly runtimeSessionWebviews: Map<vscode.Webview, { sessionId: string }> = new Map();
  private readonly runtimeGraphCache: Map<string, unknown> = new Map();

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly runtimeHub: RuntimeHub,
    private readonly postMessage: WebviewPostMessage,
    private readonly registerMessageHandling: WebviewMessageRegistrar
  ) {}

  forEachSessionPanel(cb: (panel: vscode.WebviewPanel) => void): void {
    for (const panel of this.runtimeSessionPanels.values()) cb(panel);
  }

  handleRuntimeUiMessage(message: RuntimeUiMessage): void {
    if (
      message &&
      typeof message === 'object' &&
      (message as any).type === 'runtimeDebugGraph' &&
      typeof (message as any).sessionId === 'string'
    ) {
      this.runtimeGraphCache.set((message as any).sessionId, (message as any).graph);
    }
  }

  handleRuntimeWebviewReady(webview: vscode.Webview): void {
    const snapshot: RuntimeUiMessage = {
      type: 'runtimeState',
      port: this.runtimeHub.getPort(),
      sessions: this.runtimeHub.getSessionsSnapshot()
    };
    this.postMessage(webview, snapshot);

    const meta = this.runtimeSessionWebviews.get(webview);
    const shouldReplaySession = meta?.sessionId;
    const replayTargets: string[] = [];
    if (shouldReplaySession) {
      replayTargets.push(shouldReplaySession);
    } else {
      // Main UI: replay history for debug sessions and active subscribed sessions.
      for (const s of snapshot.sessions) {
        if (s.mode === 'debug' || s.subscribed) replayTargets.push(s.id);
      }
    }

    for (const sessionId of replayTargets) {
      if (this.runtimeGraphCache.has(sessionId)) {
        this.postMessage(webview, {
          type: 'runtimeDebugGraph',
          sessionId,
          graph: this.runtimeGraphCache.get(sessionId)
        });
      }
      const hist = this.runtimeHub.getNodeEventHistory(sessionId);
      if (hist && hist.events.length > 0) {
        this.postMessage(webview, {
          type: 'runtimeHistory',
          sessionId,
          nodeEvents: hist.events.map((e) => ({
            node: e.node,
            event: e.event,
            ts: e.ts,
            runId: e.runId,
            inputs: e.inputs,
            outputs: e.outputs,
            metrics: e.metrics,
            error: e.error
          })),
          dropped: hist.dropped || undefined
        });
      } else if (hist && hist.dropped > 0) {
        this.postMessage(webview, {
          type: 'runtimeLog',
          sessionId,
          level: 'warn',
          message: `[runtime] history replay truncated: dropped=${hist.dropped}`,
          channel: 'system',
          ts: Date.now()
        });
      }

      const flowHist = this.runtimeHub.getFlowHistory(sessionId);
      if (flowHist && flowHist.flows.length > 0) {
        this.postMessage(webview, {
          type: 'runtimeFlowHistory',
          sessionId,
          flows: flowHist.flows.map((f) => ({
            ts: f.ts,
            kind: f.kind,
            from: f.from,
            to: f.to,
            node: f.node,
            scope: f.scope,
            keys: f.keys,
            keysDetails: f.keysDetails,
            message: f.message,
            values: f.values,
            changes: f.changes,
            totalKeys: f.totalKeys,
            truncated: f.truncated
          }))
        });
      }

      const logHist = this.runtimeHub.getProgramLogHistory(sessionId);
      if (logHist && logHist.logs.length > 0) {
        for (const l of logHist.logs) {
          this.postMessage(webview, l);
        }
      } else if (logHist && logHist.dropped > 0) {
        this.postMessage(webview, {
          type: 'runtimeLog',
          sessionId,
          level: 'warn',
          message: `[runtime] program logs truncated: dropped=${logHist.dropped}`,
          channel: 'system',
          ts: Date.now()
        });
      }
    }
  }

  openRuntimeSessionPanel(sessionId: string): void {
    const existing = this.runtimeSessionPanels.get(sessionId);
    if (existing) {
      existing.reveal();
      return;
    }

    const subscriberId = `runtimeSession:${sessionId}:${Date.now()}:${Math.random().toString(16).slice(2)}`;

    const snapshot = this.runtimeHub.getSessionsSnapshot();
    const session = snapshot.find((s) => s.id === sessionId);
    const titleParts: string[] = [];
    if (session?.graphName) titleParts.push(session.graphName);
    if (session?.pid) titleParts.push(`pid:${session.pid}`);
    const title = titleParts.length > 0 ? `MASFactory Visualizer: ${titleParts.join(' ')}` : `MASFactory Visualizer: ${sessionId}`;

    const panel = vscode.window.createWebviewPanel('masfactoryVisualizerRuntimeSession', title, vscode.ViewColumn.Beside, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, 'media')]
    });

    panel.webview.html = buildWebviewHtml({
      webview: panel.webview,
      extensionPath: this.context.extensionPath,
      extensionUri: this.context.extensionUri,
      bootstrap: {
        kind: 'runtime-session',
        sessionId
      }
    });

    this.registerMessageHandling(panel.webview, subscriberId);
    this.runtimeSessionWebviews.set(panel.webview, { sessionId });
    this.runtimeSessionPanels.set(sessionId, panel);

    panel.onDidDispose(() => {
      this.runtimeSessionPanels.delete(sessionId);
      this.runtimeSessionWebviews.delete(panel.webview);
      try {
        this.runtimeHub.releaseSubscriber(subscriberId);
      } catch {
        // ignore
      }
    });

    // Start streaming only when the user explicitly opens the session view.
    this.runtimeHub.subscribe(sessionId, subscriberId);
  }
}
