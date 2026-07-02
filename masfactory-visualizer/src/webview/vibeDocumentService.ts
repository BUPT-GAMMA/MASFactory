import * as vscode from 'vscode';

export type WebviewPostMessage = (target: vscode.Webview, message: unknown) => void;

type VibeSaveWrite = {
  documentUri?: unknown;
  filePath?: unknown;
  text?: unknown;
};

export class VibeDocumentService {
  constructor(private readonly postMessage: WebviewPostMessage) {}

  private writeUri(write: VibeSaveWrite): vscode.Uri | null {
    if (typeof write.documentUri === 'string' && write.documentUri.trim()) {
      return vscode.Uri.parse(write.documentUri.trim());
    }
    if (typeof write.filePath === 'string' && write.filePath.trim()) {
      return vscode.Uri.file(write.filePath.trim());
    }
    return null;
  }

  private async saveText(uri: vscode.Uri, text: string): Promise<void> {
    const doc = await vscode.workspace.openTextDocument(uri);
    const fullRange = new vscode.Range(new vscode.Position(0, 0), doc.positionAt(doc.getText().length));
    const edit = new vscode.WorkspaceEdit();
    edit.replace(uri, fullRange, text);
    await vscode.workspace.applyEdit(edit);
    await doc.save();
  }

  async save(
    webview: vscode.Webview,
    payload: { documentUri?: unknown; text?: unknown; extraWrites?: unknown }
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
      await this.saveText(uri, nextText);
      const extraWrites = Array.isArray(payload.extraWrites) ? payload.extraWrites : [];
      for (const item of extraWrites) {
        const write = item as VibeSaveWrite;
        if (typeof write.text !== 'string') {continue;}
        const writeUri = this.writeUri(write);
        if (!writeUri) {continue;}
        await this.saveText(writeUri, write.text);
      }

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
