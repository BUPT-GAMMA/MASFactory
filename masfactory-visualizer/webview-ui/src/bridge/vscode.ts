import { PROTOCOL_VERSION } from '@shared/protocolVersion';

export interface VsCodeApi {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
}

declare global {
  interface Window {
    acquireVsCodeApi?: () => VsCodeApi;
    __MASFACTORY_VISUALIZER_VSCODE_API?: VsCodeApi;
  }
}

let cached: VsCodeApi | null = null;

export function getVsCodeApi(): VsCodeApi | null {
  if (cached) return cached;
  if (window.__MASFACTORY_VISUALIZER_VSCODE_API) {
    cached = window.__MASFACTORY_VISUALIZER_VSCODE_API;
    return cached;
  }
  if (typeof window.acquireVsCodeApi !== 'function') return null;
  try {
    cached = window.acquireVsCodeApi();
    window.__MASFACTORY_VISUALIZER_VSCODE_API = cached;
  } catch {
    // In case another script already called acquireVsCodeApi() (only allowed once),
    // fall back to the shared handle if available.
    cached = window.__MASFACTORY_VISUALIZER_VSCODE_API || null;
  }
  return cached;
}

export function postMessage(message: unknown): void {
  try {
    if (message && typeof message === 'object' && !Array.isArray(message)) {
      const record = message as Record<string, unknown>;
      if (record.protocolVersion === undefined) {
        getVsCodeApi()?.postMessage({ protocolVersion: PROTOCOL_VERSION, ...record });
        return;
      }
    }
    getVsCodeApi()?.postMessage(message);
  } catch {
    // ignore
  }
}

export function onVsCodeMessage(handler: (data: any) => void): () => void {
  const listener = (event: MessageEvent) => handler(event.data);
  window.addEventListener('message', listener);
  return () => window.removeEventListener('message', listener);
}
