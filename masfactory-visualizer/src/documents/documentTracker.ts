import * as vscode from 'vscode';
import type { WebviewProvider } from '../webview/webviewProvider';

export function registerDocumentListeners(args: {
  context: vscode.ExtensionContext;
  webviewProvider: WebviewProvider;
}): void {
  const { context, webviewProvider } = args;
  const isJsonLang = (id: string): boolean => id === 'json' || id === 'jsonc';

  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor && editor.document.languageId === 'python') {
        webviewProvider.setLastActivePythonDocument(editor.document);
        webviewProvider.updateGraph(editor.document);
      } else if (editor && isJsonLang(editor.document.languageId)) {
        webviewProvider.setLastActiveVibeDocument(editor.document);
        webviewProvider.updateVibeDocument(editor.document);
      }
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument((document) => {
      if (vscode.window.activeTextEditor?.document !== document) return;
      if (document.languageId === 'python') {
        webviewProvider.setLastActivePythonDocument(document);
        webviewProvider.updateGraph(document);
        return;
      }
      if (isJsonLang(document.languageId)) {
        webviewProvider.setLastActiveVibeDocument(document);
        webviewProvider.updateVibeDocument(document);
      }
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument((event) => {
      const doc = event.document;
      if (doc.languageId === 'python') {
        if (webviewProvider.isLastActivePythonDocument(doc)) webviewProvider.updateGraph(doc);
        return;
      }
      if (isJsonLang(doc.languageId)) {
        if (webviewProvider.isLastActiveVibeDocument(doc)) webviewProvider.updateVibeDocument(doc);
      }
    })
  );

  // Trigger initial update on activation.
  const activeDoc = vscode.window.activeTextEditor?.document;
  if (activeDoc?.languageId === 'python') {
    webviewProvider.setLastActivePythonDocument(activeDoc);
    webviewProvider.updateGraph(activeDoc);
  } else if (activeDoc && isJsonLang(activeDoc.languageId)) {
    webviewProvider.setLastActiveVibeDocument(activeDoc);
    webviewProvider.updateVibeDocument(activeDoc);
  }
}
