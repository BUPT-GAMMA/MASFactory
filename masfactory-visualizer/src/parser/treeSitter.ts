import * as fs from 'fs';
import * as path from 'path';
import { Language, Parser } from 'web-tree-sitter';

let initPromise: Promise<void> | null = null;
let pythonLanguage: Language | null = null;

function getWasmDir(extensionPath: string): string {
  return path.join(extensionPath, 'media');
}

function assertFileExists(filePath: string, label: string): void {
  if (fs.existsSync(filePath)) return;
  throw new Error(`[TreeSitter] Missing ${label} at: ${filePath}`);
}

/**
 * Initialize web-tree-sitter and load the Python grammar WASM.
 *
 * This must be called once before any parsing occurs.
 */
export async function initTreeSitter(extensionPath: string): Promise<void> {
  if (initPromise) return initPromise;

  initPromise = (async () => {
    const wasmDir = getWasmDir(extensionPath);
    const engineWasmPath = path.join(wasmDir, 'tree-sitter.wasm');
    const pythonWasmPath = path.join(wasmDir, 'tree-sitter-python.wasm');

    assertFileExists(engineWasmPath, 'Tree-sitter engine WASM (tree-sitter.wasm)');
    assertFileExists(pythonWasmPath, 'Python grammar WASM (tree-sitter-python.wasm)');

    await Parser.init({
      locateFile: (fileName: string) => path.join(wasmDir, fileName)
    });

    pythonLanguage = await Language.load(pythonWasmPath);
  })();

  return initPromise;
}

export function isTreeSitterReady(): boolean {
  return pythonLanguage !== null;
}

export function createPythonParser(): Parser | null {
  // `web-tree-sitter` requires `Parser.init()` before any `new Parser()` calls.
  // So we only construct the parser after initTreeSitter() has successfully loaded the language.
  if (!pythonLanguage) return null;

  const parser = new Parser();
  try {
    parser.setLanguage(pythonLanguage);
  } catch (err) {
    console.error('[TreeSitter] Failed to assign Python language to parser:', err);
    return null;
  }
  return parser;
}
