import * as vscode from 'vscode';
import type { WebviewProvider } from '../webview/webviewProvider';

function isVibeDocument(document: vscode.TextDocument): boolean {
  const languageId = document.languageId;
  if (languageId === 'json' || languageId === 'jsonc' || languageId === 'aml') {
    return true;
  }
  return document.uri.fsPath.toLowerCase().endsWith('.aml');
}

export function registerDocumentListeners(args: {
  context: vscode.ExtensionContext;
  webviewProvider: WebviewProvider;
}): void {
  const { context, webviewProvider } = args;

  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor && editor.document.languageId === 'python') {
        webviewProvider.setLastActivePythonDocument(editor.document);
        webviewProvider.updateGraph(editor.document);
      } else if (editor && isVibeDocument(editor.document)) {
        webviewProvider.setLastActiveVibeDocument(editor.document);
        webviewProvider.updateVibeDocument(editor.document);
      }
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument((document) => {
      if (vscode.window.activeTextEditor?.document !== document) {
        return;
      }
      if (document.languageId === 'python') {
        webviewProvider.setLastActivePythonDocument(document);
        webviewProvider.updateGraph(document);
        return;
      }
      if (isVibeDocument(document)) {
        webviewProvider.setLastActiveVibeDocument(document);
        webviewProvider.updateVibeDocument(document);
      }
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument((event) => {
      const doc = event.document;
      if (doc.languageId === 'python') {
        if (webviewProvider.isLastActivePythonDocument(doc)) {
          webviewProvider.updateGraph(doc);
        }
        return;
      }
      if (isVibeDocument(doc)) {
        if (webviewProvider.isLastActiveVibeDocument(doc)) {
          webviewProvider.updateVibeDocument(doc);
        }
      }
    })
  );

  // Trigger initial update on activation.
  const activeDoc = vscode.window.activeTextEditor?.document;
  if (activeDoc?.languageId === 'python') {
    webviewProvider.setLastActivePythonDocument(activeDoc);
    webviewProvider.updateGraph(activeDoc);
  } else if (activeDoc && isVibeDocument(activeDoc)) {
    webviewProvider.setLastActiveVibeDocument(activeDoc);
    webviewProvider.updateVibeDocument(activeDoc);
  }
}
