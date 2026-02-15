import * as vscode from 'vscode';
import { parseWebviewMessage } from './webviewMessages';

export type WebviewMessageHandlers = {
  navigateToLine: (uriString: string, lineNumber: number) => void;
  templateSelectionChanged: (documentUri: string | undefined, templateName: string | null) => Promise<void>;
  conditionChanged: (
    webview: vscode.Webview,
    documentUri: string | undefined,
    conditions: { [key: string]: boolean }
  ) => Promise<void>;
  loopIterationsChanged: (
    webview: vscode.Webview,
    documentUri: string | undefined,
    loopIterations: Record<string, number>,
    conditions: Record<string, boolean> | undefined
  ) => Promise<void>;
  adjacencyGraphChanged: (
    webview: vscode.Webview,
    documentUri: string | undefined,
    graphVariable: string,
    edges: Array<{ from: number; to: number; keys?: Record<string, string> }>,
    conditions: Record<string, boolean> | undefined,
    loopIterations: Record<string, number> | undefined
  ) => Promise<void>;
  refreshGraph: (documentUri?: string) => Promise<void>;
  resetViewState: (documentUri?: string) => Promise<void>;
  webviewReady: () => void;
  runtimeWebviewReady: (webview: vscode.Webview) => void;
  runtimeSubscribe: (sessionId: string) => void;
  runtimeUnsubscribe: (sessionId: string) => void;
  runtimeOpenSession: (sessionId: string) => void;
  runtimeHumanResponse: (sessionId: string, requestId: string, content: string) => void;
  openFileLocation: (filePath?: unknown, line?: unknown, column?: unknown) => void;
  vibeSave: (webview: vscode.Webview, documentUri?: unknown, text?: unknown) => Promise<void>;
  vibeReload: (documentUri?: unknown) => Promise<void>;
};

export function registerWebviewMessageHandling(args: {
  context: vscode.ExtensionContext;
  webview: vscode.Webview;
  subscriberId: string;
  handlers: WebviewMessageHandlers;
}): void {
  const { context, webview, subscriberId, handlers } = args;

  webview.onDidReceiveMessage(
    (raw) => {
      const message = parseWebviewMessage(raw);
      if (!message) return;
      switch (message.type) {
        case 'navigateToLine':
          handlers.navigateToLine(message.uri, message.lineNumber);
          return;
        case 'templateSelectionChanged':
          void handlers.templateSelectionChanged(message.documentUri, message.templateName);
          return;
        case 'conditionChanged':
          void handlers.conditionChanged(webview, message.documentUri, message.conditions);
          return;
        case 'loopIterationsChanged':
          void handlers.loopIterationsChanged(
            webview,
            message.documentUri,
            message.loopIterations || {},
            message.conditions
          );
          return;
        case 'adjacencyGraphChanged':
          void handlers.adjacencyGraphChanged(
            webview,
            message.documentUri,
            message.graphVariable,
            message.edges,
            message.conditions,
            message.loopIterations
          );
          return;
        case 'refreshGraph':
          void handlers.refreshGraph(message.documentUri);
          return;
        case 'resetViewState':
          void handlers.resetViewState(message.documentUri);
          return;
        case 'webviewReady':
          handlers.webviewReady();
          return;
        case 'runtimeWebviewReady':
          handlers.runtimeWebviewReady(webview);
          return;
        case 'runtimeSubscribe':
          handlers.runtimeSubscribe(message.sessionId);
          return;
        case 'runtimeUnsubscribe':
          handlers.runtimeUnsubscribe(message.sessionId);
          return;
        case 'runtimeOpenSession':
          handlers.runtimeOpenSession(message.sessionId);
          return;
        case 'runtimeHumanResponse':
          handlers.runtimeHumanResponse(message.sessionId, message.requestId, message.content);
          return;
        case 'openFileLocation':
          handlers.openFileLocation(message.filePath, message.line, message.column);
          return;
        case 'vibeSave':
          void handlers.vibeSave(webview, message.documentUri, message.text);
          return;
        case 'vibeReload':
          void handlers.vibeReload(message.documentUri);
          return;
      }
    },
    undefined,
    context.subscriptions
  );

  void subscriberId;
}
