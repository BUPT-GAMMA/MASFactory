export type VisualizerMode = 'debug' | 'run' | 'unknown';

export interface DebugLocation {
  path?: string;
  line?: number;
  column?: number;
  name?: string;
}

export interface DebugExceptionInfo {
  id?: string;
  description?: string;
  details?: unknown;
}

export interface VisualizerSession {
  id: string;
  pid: number | null;
  graphName: string | null;
  mode: VisualizerMode;
  connectedAt: number;
  lastSeenAt: number;
  subscribed: boolean;
}

export type RuntimeUiMessage =
  | {
      type: 'runtimeState';
      port: number | null;
      sessions: VisualizerSession[];
    }
  | {
      type: 'runtimeHumanRequest';
      sessionId: string;
      requestId: string;
      node?: string;
      field?: string;
      description?: string;
      prompt: string;
      ts: number;
    }
  | {
      type: 'runtimeHistory';
      sessionId: string;
      nodeEvents: Array<{
        node: string;
        event: 'start' | 'end' | 'error';
        ts: number;
        runId?: string;
        inputs?: unknown;
        outputs?: unknown;
        metrics?: unknown;
        error?: string;
      }>;
      dropped?: number;
      truncated?: number;
    }
  | {
      type: 'runtimeDebugStopped';
      pid: number | null;
      sessionId?: string;
      reason: string;
      description?: string;
      threadId?: number;
      allThreadsStopped?: boolean;
      location?: DebugLocation;
      exception?: DebugExceptionInfo;
      ts: number;
    }
  | {
      type: 'runtimeDebugContinued';
      pid: number | null;
      sessionId?: string;
      threadId?: number;
      allThreadsContinued?: boolean;
      ts: number;
    }
  | {
      type: 'runtimeAutoTab';
      tab: 'debug' | 'run';
      sessionId: string;
    }
  | {
      type: 'runtimeDebugGraph';
      sessionId: string;
      graph: unknown;
    }
  | {
      type: 'runtimeNodeEvent';
      sessionId: string;
      node: string;
      event: 'start' | 'end' | 'error';
      ts: number;
      runId?: string;
      inputs?: unknown;
      outputs?: unknown;
      metrics?: unknown;
      error?: string;
    }
  | {
      type: 'runtimeLog';
      sessionId?: string;
      level: 'info' | 'warn' | 'error';
      message: string;
      channel?: 'program' | 'system';
      ts?: number;
    }
  | {
      type: 'runtimeFlow';
      sessionId: string;
      ts: number;
      kind: string;
      from?: string;
      to?: string;
      node?: string;
      scope?: string;
      keys?: string[];
      keysDetails?: Record<string, string>;
      message?: unknown;
      values?: unknown;
      changes?: unknown;
      totalKeys?: number;
      truncated?: boolean;
    }
  | {
      type: 'runtimeFlowHistory';
      sessionId: string;
      flows: Array<Omit<Extract<RuntimeUiMessage, { type: 'runtimeFlow' }>, 'type' | 'sessionId'>>;
    }
  | {
      type: 'runtimeTrace';
      sessionId: string;
      dir: 'in' | 'out';
      messageType: string;
      payload?: unknown;
      ts: number;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function asOptionalString(value: unknown): string | undefined {
  const s = asString(value);
  return s ?? undefined;
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function asOptionalNumber(value: unknown): number | undefined {
  const n = asNumber(value);
  return n ?? undefined;
}

function asRequiredNumber(value: unknown): number | null {
  return asNumber(value);
}

function asMode(value: unknown): VisualizerMode {
  const s = typeof value === 'string' ? value.toLowerCase() : '';
  if (s === 'debug') return 'debug';
  if (s === 'run') return 'run';
  return 'unknown';
}

function parseSessions(value: unknown): VisualizerSession[] {
  if (!Array.isArray(value)) return [];
  const out: VisualizerSession[] = [];
  for (const it of value) {
    if (!isRecord(it)) continue;
    const id = asString(it.id);
    if (!id) continue;
    const pid = it.pid === null ? null : asNumber(it.pid);
    const graphName = typeof it.graphName === 'string' ? it.graphName : it.graphName === null ? null : null;
    const connectedAt = asRequiredNumber(it.connectedAt);
    const lastSeenAt = asRequiredNumber(it.lastSeenAt);
    const subscribed = typeof it.subscribed === 'boolean' ? it.subscribed : false;
    if (connectedAt === null || lastSeenAt === null) continue;
    out.push({
      id,
      pid,
      graphName,
      mode: asMode(it.mode),
      connectedAt,
      lastSeenAt,
      subscribed
    });
  }
  return out;
}

function parseDebugLocation(value: unknown): DebugLocation | undefined {
  if (!isRecord(value)) return undefined;
  const out: DebugLocation = {};
  if (typeof value.path === 'string' && value.path) out.path = value.path;
  if (typeof value.line === 'number' && Number.isFinite(value.line)) out.line = value.line;
  if (typeof value.column === 'number' && Number.isFinite(value.column)) out.column = value.column;
  if (typeof value.name === 'string' && value.name) out.name = value.name;
  return out;
}

function parseDebugException(value: unknown): DebugExceptionInfo | undefined {
  if (!isRecord(value)) return undefined;
  const out: DebugExceptionInfo = {};
  if (typeof value.id === 'string' && value.id) out.id = value.id;
  if (typeof value.description === 'string' && value.description) out.description = value.description;
  if (value.details !== undefined) out.details = value.details;
  return out;
}

export function parseRuntimeMessage(raw: unknown): RuntimeUiMessage | null {
  if (!isRecord(raw)) return null;
  const type = asString(raw.type);
  if (!type || !type.startsWith('runtime')) return null;

  if (type === 'runtimeState') {
    const port = raw.port === undefined || raw.port === null ? null : asNumber(raw.port);
    const sessions = parseSessions(raw.sessions);
    if (port === null && raw.port !== undefined && raw.port !== null) return null;
    return { type, port, sessions };
  }

  if (type === 'runtimeHumanRequest') {
    const sessionId = asString(raw.sessionId);
    const requestId = asString(raw.requestId);
    const prompt = typeof raw.prompt === 'string' ? raw.prompt : null;
    const ts = asRequiredNumber(raw.ts);
    if (!sessionId || !requestId || prompt === null || ts === null) return null;
    return {
      type,
      sessionId,
      requestId,
      node: asOptionalString(raw.node),
      field: asOptionalString(raw.field),
      description: asOptionalString(raw.description),
      prompt,
      ts
    };
  }

  if (type === 'runtimeHistory') {
    const sessionId = asString(raw.sessionId);
    if (!sessionId) return null;
    const nodeEvents: Array<any> = Array.isArray(raw.nodeEvents) ? raw.nodeEvents : [];
    const events = nodeEvents
      .filter((e) => isRecord(e) && typeof e.node === 'string' && typeof e.event === 'string')
      .map((e) => ({
        node: String(e.node),
        event: e.event === 'start' || e.event === 'end' || e.event === 'error' ? e.event : null,
        ts: asNumber(e.ts) ?? Date.now(),
        runId: typeof e.runId === 'string' ? e.runId : undefined,
        inputs: (e as any).inputs,
        outputs: (e as any).outputs,
        metrics: (e as any).metrics,
        error: typeof (e as any).error === 'string' ? (e as any).error : undefined
      }))
      .filter((e) => !!e.event);
    return {
      type,
      sessionId,
      nodeEvents: events,
      dropped: asOptionalNumber(raw.dropped),
      truncated: asOptionalNumber(raw.truncated)
    };
  }

  if (type === 'runtimeDebugStopped') {
    const pid = raw.pid === null ? null : asNumber(raw.pid);
    const reason = asString(raw.reason);
    const ts = asRequiredNumber(raw.ts);
    if (!reason || ts === null) return null;
    return {
      type,
      pid,
      sessionId: asOptionalString(raw.sessionId),
      reason,
      description: asOptionalString(raw.description),
      threadId: asOptionalNumber(raw.threadId),
      allThreadsStopped: typeof raw.allThreadsStopped === 'boolean' ? raw.allThreadsStopped : undefined,
      location: parseDebugLocation(raw.location),
      exception: parseDebugException(raw.exception),
      ts
    };
  }

  if (type === 'runtimeDebugContinued') {
    const pid = raw.pid === null ? null : asNumber(raw.pid);
    const ts = asRequiredNumber(raw.ts);
    if (ts === null) return null;
    return {
      type,
      pid,
      sessionId: asOptionalString(raw.sessionId),
      threadId: asOptionalNumber(raw.threadId),
      allThreadsContinued: typeof raw.allThreadsContinued === 'boolean' ? raw.allThreadsContinued : undefined,
      ts
    };
  }

  if (type === 'runtimeAutoTab') {
    const tab = raw.tab === 'debug' || raw.tab === 'run' ? raw.tab : null;
    const sessionId = asString(raw.sessionId);
    if (!tab || !sessionId) return null;
    return { type, tab, sessionId };
  }

  if (type === 'runtimeDebugGraph') {
    const sessionId = asString(raw.sessionId);
    if (!sessionId) return null;
    return { type, sessionId, graph: raw.graph };
  }

  if (type === 'runtimeNodeEvent') {
    const sessionId = asString(raw.sessionId);
    const node = asString(raw.node);
    const ev = raw.event === 'start' || raw.event === 'end' || raw.event === 'error' ? raw.event : null;
    const ts = asRequiredNumber(raw.ts);
    if (!sessionId || !node || !ev || ts === null) return null;
    return {
      type,
      sessionId,
      node,
      event: ev,
      ts,
      runId: asOptionalString(raw.runId),
      inputs: raw.inputs,
      outputs: raw.outputs,
      metrics: raw.metrics,
      error: typeof raw.error === 'string' ? raw.error : undefined
    };
  }

  if (type === 'runtimeLog') {
    const level = raw.level === 'info' || raw.level === 'warn' || raw.level === 'error' ? raw.level : null;
    const message = typeof raw.message === 'string' ? raw.message : null;
    if (!level || message === null) return null;
    const channel = raw.channel === 'program' || raw.channel === 'system' ? raw.channel : undefined;
    const ts = asOptionalNumber(raw.ts);
    const sessionId = typeof raw.sessionId === 'string' ? raw.sessionId : undefined;
    return { type, sessionId, level, message, channel, ts };
  }

  if (type === 'runtimeFlow') {
    const sessionId = asString(raw.sessionId);
    const kind = asString(raw.kind);
    const ts = asRequiredNumber(raw.ts);
    if (!sessionId || !kind || ts === null) return null;
    const keysDetails = isRecord(raw.keysDetails)
      ? Object.fromEntries(Object.entries(raw.keysDetails).map(([k, v]) => [String(k), v == null ? '' : String(v)]))
      : undefined;
    const keys = Array.isArray(raw.keys)
      ? raw.keys
          .map((x) => {
            if (typeof x === 'string') return x;
            if (typeof x === 'number' && Number.isFinite(x)) return String(x);
            if (typeof x === 'boolean') return x ? 'true' : 'false';
            if (typeof x === 'bigint') return String(x);
            return null;
          })
          .filter((x): x is string => typeof x === 'string')
      : undefined;
    return {
      type,
      sessionId,
      ts,
      kind,
      from: asOptionalString(raw.from),
      to: asOptionalString(raw.to),
      node: asOptionalString(raw.node),
      scope: asOptionalString(raw.scope),
      keys,
      keysDetails,
      message: raw.message,
      values: raw.values,
      changes: raw.changes,
      totalKeys: asOptionalNumber(raw.totalKeys),
      truncated: typeof raw.truncated === 'boolean' ? raw.truncated : undefined
    };
  }

  if (type === 'runtimeFlowHistory') {
    const sessionId = asString(raw.sessionId);
    if (!sessionId) return null;
    const flows = Array.isArray(raw.flows) ? raw.flows.filter((x) => isRecord(x)) : [];
    return { type, sessionId, flows: flows as any };
  }

  if (type === 'runtimeTrace') {
    const sessionId = asString(raw.sessionId);
    const dir = raw.dir === 'in' || raw.dir === 'out' ? raw.dir : null;
    const messageType = asString(raw.messageType);
    const ts = asRequiredNumber(raw.ts);
    if (!sessionId || !dir || !messageType || ts === null) return null;
    return { type, sessionId, dir, messageType, payload: raw.payload, ts };
  }

  return null;
}
