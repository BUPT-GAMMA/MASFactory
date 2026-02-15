import * as vscode from 'vscode';

export type WebviewPostMessage = (target: vscode.Webview, message: unknown) => void;

export class VibeDocumentService {
  constructor(private readonly postMessage: WebviewPostMessage) {}

  async save(
    webview: vscode.Webview,
    payload: { documentUri?: unknown; text?: unknown }
  ): Promise<void> {
    const uriStr = typeof payload.documentUri === 'string' ? payload.documentUri : '';
    if (!uriStr || typeof payload.text !== 'string') {
      this.postMessage(webview, {
        type: 'vibeSaveResult',
        documentUri: uriStr,
        ok: false,
        error: 'Missing documentUri/text'
      });
      return;
    }
    const nextText = payload.text;

    let uri: vscode.Uri;
    try {
      uri = vscode.Uri.parse(uriStr);
    } catch (err) {
      this.postMessage(webview, {
        type: 'vibeSaveResult',
        documentUri: uriStr,
        ok: false,
        error: `Invalid URI: ${String(err)}`
      });
      return;
    }

    try {
      const doc = await vscode.workspace.openTextDocument(uri);
      const fullRange = new vscode.Range(new vscode.Position(0, 0), doc.positionAt(doc.getText().length));
      const edit = new vscode.WorkspaceEdit();
      edit.replace(uri, fullRange, nextText);
      await vscode.workspace.applyEdit(edit);
      await doc.save();

      this.postMessage(webview, {
        type: 'vibeSaveResult',
        documentUri: uriStr,
        ok: true
      });
    } catch (err) {
      this.postMessage(webview, {
        type: 'vibeSaveResult',
        documentUri: uriStr,
        ok: false,
        error: String(err)
      });
    }
  }

  async reload(payload: { documentUri?: unknown }): Promise<vscode.TextDocument | null> {
    const uriStr = typeof payload.documentUri === 'string' ? payload.documentUri : '';
    if (!uriStr) {
      void vscode.window.showWarningMessage('MASFactory Visualizer: reload failed (missing documentUri).');
      return null;
    }
    try {
      return await vscode.workspace.openTextDocument(vscode.Uri.parse(uriStr));
    } catch (err) {
      void vscode.window.showWarningMessage(`MASFactory Visualizer: reload failed: ${String(err)}`);
      return null;
    }
  }
}
