import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

function getMissingWebviewBuildHtml(extensionPath: string, distDir: string): string {
  const relative = path.relative(extensionPath, distDir) || distDir;
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>MASFactory Visualizer</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; padding: 16px; }
    code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; }
  </style>
</head>
<body>
  <h2>MASFactory Visualizer Webview UI not built</h2>
  <p>Missing <code>${relative}/index.html</code>.</p>
  <p>Build it with:</p>
  <pre><code>cd masfactory-visualizer/webview-ui
npm install
npm run build</code></pre>
</body>
</html>`;
}

function getNonce(): string {
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let nonce = '';
  for (let i = 0; i < 32; i++) {
    nonce += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return nonce;
}

function getExtensionVersion(extensionPath: string): string | null {
  try {
    const pkgPath = path.join(extensionPath, 'package.json');
    const raw = fs.readFileSync(pkgPath, 'utf-8');
    const pkg = JSON.parse(raw);
    if (pkg && typeof pkg.version === 'string' && pkg.version.trim()) return pkg.version.trim();
  } catch {
    // ignore
  }
  return null;
}

export function buildWebviewHtml(args: {
  webview: vscode.Webview;
  extensionPath: string;
  extensionUri: vscode.Uri;
  bootstrap?: unknown;
}): string {
  const { webview, extensionPath, extensionUri, bootstrap } = args;
  try {
    const distDir = path.join(extensionPath, 'media', 'webview-ui');
    const indexPath = path.join(distDir, 'index.html');
    if (!fs.existsSync(indexPath)) {
      return getMissingWebviewBuildHtml(extensionPath, distDir);
    }

    const nonce = getNonce();
    let html = fs.readFileSync(indexPath, 'utf-8');

    const csp = [
      `default-src 'none';`,
      `img-src ${webview.cspSource} https: data:;`,
      `style-src ${webview.cspSource} 'unsafe-inline';`,
      `script-src 'nonce-${nonce}' ${webview.cspSource};`,
      `font-src ${webview.cspSource};`,
      `connect-src ${webview.cspSource};`
    ].join(' ');

    const bootstrapSnippet =
      bootstrap !== undefined
        ? `window.__MASFACTORY_VISUALIZER_BOOTSTRAP=${JSON.stringify(bootstrap)};`
        : '';
    const version = getExtensionVersion(extensionPath);
    const metaSnippet = version
      ? `window.__MASFACTORY_VISUALIZER_META=${JSON.stringify({ version })};`
      : '';
    const preludeSnippet = `${metaSnippet}${bootstrapSnippet}`;

    html = html.replace(
      /<head>/i,
      `<head>\n<meta http-equiv="Content-Security-Policy" content="${csp}">\n` +
        `<script nonce="${nonce}">${preludeSnippet}</script>`
    );

    const rewriteUri = (raw: string): string => {
      if (raw.startsWith('http:') || raw.startsWith('https:') || raw.startsWith('data:') || raw.startsWith('#')) {
        return raw;
      }
      const clean = raw.replace(/^\//, '').replace(/^\.\//, '');
      const onDisk = vscode.Uri.file(path.join(distDir, clean));
      return webview.asWebviewUri(onDisk).toString();
    };

    html = html.replace(/(src|href)=\"([^\"]+)\"/g, (_match, attr, value) => {
      return `${attr}="${rewriteUri(value)}"`;
    });

    // Ensure all script tags carry the nonce (Vite uses external module scripts in production build).
    html = html.replace(/<script\b(?![^>]*\bnonce=)/g, `<script nonce="${nonce}"`);

    return html;
  } catch (error) {
    console.error('[MASFactory Visualizer] Error loading webview content:', error);
    return `
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <title>MASFactory Visualizer Error</title>
                </head>
                <body>
                    <h2>Failed to load view</h2>
                    <p>Unable to load MASFactory Visualizer webview content.</p>
                    <p>Error: ${error}</p>
                </body>
                </html>
            `;
  }
}
