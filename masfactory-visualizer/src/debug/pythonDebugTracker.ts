import * as vscode from 'vscode';
import type { RuntimeHub } from '../runtime/runtimeHub';

export function registerPythonDebugAdapterTracking(args: {
  context: vscode.ExtensionContext;
  runtimeHub: RuntimeHub;
  debugTypes: readonly string[];
}): void {
  const { context, runtimeHub, debugTypes } = args;
  const pidByDebugSessionId = new Map<string, number>();

  const asNumber = (v: unknown): number | undefined =>
    typeof v === 'number' && Number.isFinite(v) ? v : undefined;
  const asString = (v: unknown): string | undefined =>
    typeof v === 'string' && v.trim() ? v : undefined;

  const tryResolvePilotSessionId = (pid: number | null): string | undefined => {
    if (pid === null) return undefined;
    try {
      const sessions = runtimeHub.getSessionsSnapshot();
      return sessions.find((s) => s.pid === pid)?.id;
    } catch {
      return undefined;
    }
  };

  const publishStopped = async (debugSession: vscode.DebugSession, stoppedBody: any) => {
    const threadId = asNumber(stoppedBody?.threadId);
    const reason = asString(stoppedBody?.reason) ?? 'stopped';
    const description = asString(stoppedBody?.description);
    const allThreadsStopped = stoppedBody?.allThreadsStopped === true;

    let pid = pidByDebugSessionId.get(debugSession.id) ?? null;
    let pilotSessionId = tryResolvePilotSessionId(pid);

    let location: { path?: string; line?: number; column?: number; name?: string } | undefined;
    let frameId: number | undefined;
    if (threadId !== undefined) {
      try {
        const stack: any = await debugSession.customRequest('stackTrace', {
          threadId,
          startFrame: 0,
          levels: 1
        });
        const frame = Array.isArray(stack?.stackFrames) ? stack.stackFrames[0] : null;
        const source = frame?.source;
        const path = asString(source?.path);
        const line = asNumber(frame?.line);
        const column = asNumber(frame?.column);
        const name = asString(source?.name);
        frameId = asNumber(frame?.id);
        location = { path, line, column, name };
      } catch (err) {
        runtimeHub.publishUi({
          type: 'runtimeLog',
          level: 'warn',
          message: `[debug] stackTrace failed: ${String(err)}`,
          channel: 'system',
          ts: Date.now()
        });
      }
    }

    // Best-effort pid recovery for adapters that don't send systemProcessId.
    if (pid === null && threadId !== undefined) {
      try {
        const evaluated: any = await debugSession.customRequest('evaluate', {
          expression: '__import__("os").getpid()',
          context: 'repl',
          frameId
        });
        const raw =
          typeof evaluated?.result === 'string' ? evaluated.result : String(evaluated?.result ?? '');
        const n = Number(raw);
        if (Number.isFinite(n)) {
          pid = n;
          pidByDebugSessionId.set(debugSession.id, n);
          runtimeHub.markDebugPid(n);
          pilotSessionId = tryResolvePilotSessionId(n);
        }
      } catch {
        // ignore
      }
    }

    let exception: { id?: string; description?: string; details?: unknown } | undefined;
    if (reason.toLowerCase() === 'exception' && threadId !== undefined) {
      try {
        const info: any = await debugSession.customRequest('exceptionInfo', { threadId });
        exception = {
          id: asString(info?.exceptionId),
          description: asString(info?.description),
          details: info?.details
        };
      } catch (err) {
        runtimeHub.publishUi({
          type: 'runtimeLog',
          level: 'warn',
          message: `[debug] exceptionInfo failed: ${String(err)}`,
          channel: 'system',
          ts: Date.now()
        });
      }
    }

    runtimeHub.publishUi({
      type: 'runtimeDebugStopped',
      pid,
      sessionId: pilotSessionId,
      reason,
      description,
      threadId,
      allThreadsStopped,
      location,
      exception,
      ts: Date.now()
    });
  };

  const publishContinued = (debugSession: vscode.DebugSession, continuedBody: any) => {
    const pid = pidByDebugSessionId.get(debugSession.id) ?? null;
    const pilotSessionId = tryResolvePilotSessionId(pid);
    runtimeHub.publishUi({
      type: 'runtimeDebugContinued',
      pid,
      sessionId: pilotSessionId,
      threadId: asNumber(continuedBody?.threadId),
      allThreadsContinued: continuedBody?.allThreadsContinued === true,
      ts: Date.now()
    });
  };

  for (const debugType of debugTypes) {
    context.subscriptions.push(
      vscode.debug.registerDebugAdapterTrackerFactory(debugType, {
        createDebugAdapterTracker(debugSession: vscode.DebugSession) {
          return {
            onDidSendMessage(message: any) {
              if (!message || typeof message !== 'object') return;
              if (message.type !== 'event') return;
              const ev = asString(message.event) ?? '';
              const body = message.body ?? {};

              if (ev === 'process') {
                const pid = asNumber(body?.systemProcessId) ?? asNumber(body?.processId);
                if (pid !== undefined) {
                  pidByDebugSessionId.set(debugSession.id, pid);
                  runtimeHub.markDebugPid(pid);
                  runtimeHub.publishUi({
                    type: 'runtimeLog',
                    level: 'info',
                    message: `[debug] python debug session pid=${pid}`,
                    channel: 'system',
                    ts: Date.now()
                  });
                }
                return;
              }

              if (ev === 'stopped') {
                void publishStopped(debugSession, body);
                return;
              }

              if (ev === 'continued') {
                publishContinued(debugSession, body);
                return;
              }

              if (ev === 'terminated' || ev === 'exited') {
                publishContinued(debugSession, body);
                return;
              }
            },
            onWillStopSession() {
              pidByDebugSessionId.delete(debugSession.id);
            },
            onError(err: Error) {
              runtimeHub.publishUi({
                type: 'runtimeLog',
                level: 'warn',
                message: `[debug] debug adapter tracker error: ${String(err)}`,
                channel: 'system',
                ts: Date.now()
              });
            }
          };
        }
      })
    );
  }
}

