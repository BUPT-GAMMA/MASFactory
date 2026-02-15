import type { RuntimeMessage } from '../stores/runtime';
import type { AppInboundMessage } from './protocol';
import { parseAppInboundMessage } from './protocol';

export type DispatchUi = {
  setActiveTab: (tab: 'preview' | 'debug' | 'run' | 'vibe') => void;
  markRunActivity?: (sessionId: string | null | undefined) => void;
};

export type DispatchRuntime = {
  sessions: Array<{ id: string; mode?: string | null }>;
  debugSessions: Array<{ id: string }>;
  selectedSessionId: string | null;
  selectedRunSessionId: string | null;
  pinSession: (sessionId: string) => void;
  handleRuntimeMessage: (msg: RuntimeMessage) => void;
  selectDebugSession: (sessionId: string) => void;
  selectRunSession: (sessionId: string) => void;
};

export type DispatchVibe = {
  ingestDocument: (payload: { uri: string; fileName: string; text: string }) => boolean;
  applySaveResult: (payload: { uri: string; ok: boolean; error: string | null }) => void;
};

export type DispatchPreview = {
  applyUpdate: (payload: {
    documentUri: string;
    data: any;
    settings?: any;
    conditionVariables?: string[];
    loopControls?: Record<string, any>;
    loopWarnings?: string[];
    loopIterations?: Record<string, number>;
    adjacencyGraphControls?: Record<string, any>;
  }) => void;
  applyClear: (payload: { reason?: string }) => void;
};

export type DispatchContext = {
  ui: DispatchUi;
  runtime: DispatchRuntime;
  vibe: DispatchVibe;
  preview: DispatchPreview;
};

function isRunSession(ctx: DispatchContext, sessionId: string): boolean {
  if (!sessionId) return false;
  const inDebugList = ctx.runtime.debugSessions.some((s) => s.id === sessionId);
  if (inDebugList) return false;
  const session = ctx.runtime.sessions.find((s) => s.id === sessionId) || null;
  if (!session) return true; // best-effort: unknown session => treat as run
  return (session.mode || '').toLowerCase() !== 'debug';
}

export function dispatchVsCodeMessage(
  raw: unknown,
  ctx: DispatchContext,
  onFatal?: (context: string, err: unknown) => void
): void {
  let msg: AppInboundMessage | null = null;
  try {
    msg = parseAppInboundMessage(raw);
  } catch (err) {
    onFatal?.('parseAppInboundMessage', err);
    return;
  }
  if (!msg) return;

  try {
    if (msg.type === 'uiSetActiveTab') {
      ctx.ui.setActiveTab(msg.tab);
      return;
    }

    if (msg.type === 'vibeDocument') {
      const ok = ctx.vibe.ingestDocument({
        uri: msg.documentUri,
        fileName: msg.fileName,
        text: msg.text
      });
      if (ok) {
        ctx.ui.setActiveTab('vibe');
      }
      return;
    }

    if (msg.type === 'vibeSaveResult') {
      ctx.vibe.applySaveResult({
        uri: msg.documentUri,
        ok: msg.ok,
        error: msg.error ?? null
      });
      return;
    }

    if (msg.type === 'clear') {
      ctx.preview.applyClear({ reason: msg.reason });
      return;
    }

    if (msg.type === 'update') {
      ctx.preview.applyUpdate({
        documentUri: msg.documentUri,
        data: msg.data,
        settings: msg.settings,
        conditionVariables: msg.conditionVariables,
        loopControls: msg.loopControls,
        loopWarnings: msg.loopWarnings,
        loopIterations: msg.loopIterations,
        adjacencyGraphControls: msg.adjacencyGraphControls
      });
      return;
    }

    // Special case: runtimeAutoTab drives tab switching.
    if (msg.type === 'runtimeAutoTab' && (msg.tab === 'debug' || msg.tab === 'run')) {
      if (msg.tab === 'debug') {
        const sessionId = typeof (msg as any).sessionId === 'string' ? String((msg as any).sessionId) : '';
        const hasOtherDebug = !!sessionId && ctx.runtime.debugSessions.some((s) => s.id !== sessionId);
        if (!ctx.runtime.selectedSessionId && !hasOtherDebug) {
          ctx.ui.setActiveTab('debug');
          if (sessionId) ctx.runtime.selectDebugSession(sessionId);
        }
      } else {
        const sessionId = typeof (msg as any).sessionId === 'string' ? String((msg as any).sessionId) : '';
        ctx.ui.markRunActivity?.(sessionId || null);
      }
      return;
    }

    // Human interaction: forward into runtime store + best-effort focus.
    if (msg.type === 'runtimeHumanRequest') {
      const sessionId = typeof (msg as any).sessionId === 'string' ? String((msg as any).sessionId) : '';
      ctx.runtime.handleRuntimeMessage(msg as RuntimeMessage);

      if (sessionId && !ctx.runtime.selectedSessionId && !ctx.runtime.selectedRunSessionId) {
        const session = ctx.runtime.sessions.find((s) => s.id === sessionId) || null;
        const isDebug = session?.mode === 'debug' || ctx.runtime.debugSessions.some((s) => s.id === sessionId);
        if (isDebug) {
          ctx.ui.setActiveTab('debug');
          ctx.runtime.selectDebugSession(sessionId);
        } else {
          // Do not force switching to Run. Just mark activity so the user can choose to open it.
          ctx.ui.markRunActivity?.(sessionId || null);
        }
      }
      return;
    }

    if (msg.type.startsWith('runtime')) {
      ctx.runtime.handleRuntimeMessage(msg as RuntimeMessage);
      const sid = typeof (msg as any).sessionId === 'string' ? String((msg as any).sessionId) : '';
      if (sid && isRunSession(ctx, sid)) {
        ctx.ui.markRunActivity?.(sid);
      }
    }
  } catch (err) {
    onFatal?.('dispatchVsCodeMessage', err);
  }
}
