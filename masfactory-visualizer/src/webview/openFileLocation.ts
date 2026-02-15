import * as path from 'path';
import * as vscode from 'vscode';

export function openFileLocation(filePath?: unknown, line?: unknown, column?: unknown): void {
  if (typeof filePath !== 'string' || !filePath.trim()) return;
  const raw = filePath.trim();
  if (raw.startsWith('<') && raw.endsWith('>')) {
    void vscode.window.showWarningMessage(`MASFactory Visualizer: cannot open source location ${raw}`);
    return;
  }

  let uri: vscode.Uri;
  try {
    if (/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(raw)) {
      uri = vscode.Uri.parse(raw);
    } else if (path.isAbsolute(raw)) {
      uri = vscode.Uri.file(raw);
    } else {
      const root = vscode.workspace.workspaceFolders?.[0]?.uri;
      uri = root ? vscode.Uri.joinPath(root, raw) : vscode.Uri.file(raw);
    }
  } catch (err) {
    void vscode.window.showWarningMessage(
      `MASFactory Visualizer: failed to parse source location: ${raw} (${String(err)})`
    );
    return;
  }

  const lineNumber = typeof line === 'number' && Number.isFinite(line) ? line : undefined;
  const columnNumber = typeof column === 'number' && Number.isFinite(column) ? column : undefined;

  void vscode.workspace.openTextDocument(uri).then(
    (doc) =>
      vscode.window.showTextDocument(doc, { preview: false }).then((editor) => {
        if (lineNumber === undefined) return;
        const pos = new vscode.Position(
          Math.max(0, lineNumber - 1),
          Math.max(0, (columnNumber ?? 1) - 1)
        );
        editor.selection = new vscode.Selection(pos, pos);
        editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
      }),
    (err) => {
      void vscode.window.showWarningMessage(
        `MASFactory Visualizer: failed to open source location: ${raw} (${String(err)})`
      );
    }
  );
}

