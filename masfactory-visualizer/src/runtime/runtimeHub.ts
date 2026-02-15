import { EventEmitter } from 'node:events';
import { SimpleWebSocketServer, WsConnection } from './wsServer';

import type { VisualizerMode, VisualizerSession, RuntimeUiMessage } from '../shared/runtimeProtocol';
export type { VisualizerMode, VisualizerSession, RuntimeUiMessage } from '../shared/runtimeProtocol';

type SessionInternal = VisualizerSession & {
  conn: WsConnection;
  subscribers: Set<string>;
};

export type VisualizerUiCommand =
  | {
      kind: 'openFile';
      sessionId: string;
      filePath: string;
      view: 'auto' | 'preview' | 'vibe';
      reveal: boolean;
      preserveFocus: boolean;
      ts: number;
    };

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function asString(value: unknown): string | null {
  if (typeof value === 'string' && value.trim() !== '') return value;
  return null;
}

function asMode(value: unknown): VisualizerMode {
  const s = typeof value === 'string' ? value.toLowerCase() : '';
  if (s === 'debug') return 'debug';
  if (s === 'run') return 'run';
  return 'unknown';
}

function asView(value: unknown): 'auto' | 'preview' | 'vibe' {
  const s = typeof value === 'string' ? value.toLowerCase() : '';
  if (s === 'preview') return 'preview';
  if (s === 'vibe') return 'vibe';
  return 'auto';
}

export class RuntimeHub extends EventEmitter {
  private readonly server: SimpleWebSocketServer;
  private port: number | null = null;
  private readonly sessions: Map<string, SessionInternal> = new Map();
  private readonly debugPids: Set<number> = new Set();
  private readonly nodeEventHistory: Map<
    string,
    { events: Array<Extract<RuntimeUiMessage, { type: 'runtimeNodeEvent' }>>; dropped: number }
  > = new Map();
  private readonly nodeEventHistoryMax = 1500;
  private readonly flowHistory: Map<
    string,
    { flows: Array<Extract<RuntimeUiMessage, { type: 'runtimeFlow' }>>; dropped: number }
  > = new Map();
  private readonly flowHistoryMax = 2000;
  private readonly programLogHistory: Map<
    string,
    { logs: Array<Extract<RuntimeUiMessage, { type: 'runtimeLog' }>>; dropped: number }
  > = new Map();
  private readonly programLogHistoryMax = 800;

  constructor() {
    super();
    this.server = new SimpleWebSocketServer({ host: '127.0.0.1', port: 0 });
    this.server.on('connection', (conn: WsConnection) => this.onConnection(conn));
    this.server.on('error', (err) => {
      this.emitUi({
        type: 'runtimeLog',
        level: 'error',
        message: `[runtime] WebSocket server error: ${String(err)}`,
        channel: 'system',
        ts: Date.now()
      });
    });
  }

  public async start(): Promise<void> {
    if (this.port !== null) return;
    try {
      this.port = await this.server.listen();
      this.emitState();
      this.emitUi({
        type: 'runtimeLog',
        level: 'info',
        message: `[runtime] WebSocket server listening on ${this.port}`,
        channel: 'system',
        ts: Date.now()
      });
    } catch (err) {
      this.emitUi({
        type: 'runtimeLog',
        level: 'error',
        message: `[runtime] Failed to start WebSocket server: ${String(err)}`,
        channel: 'system',
        ts: Date.now()
      });
    }
  }

  public getPort(): number | null {
    return this.port;
  }

  public getSessionsSnapshot(): VisualizerSession[] {
    return Array.from(this.sessions.values()).map((s) => this.stripInternal(s));
  }

  public publishUi(message: RuntimeUiMessage): void {
    this.emitUi(message);
  }

  public markDebugPid(pid: number): void {
    if (!Number.isFinite(pid)) return;
    this.debugPids.add(pid);
    let changed = false;
    for (const s of this.sessions.values()) {
      if (s.pid !== pid) continue;
      if (s.mode !== 'debug') {
        s.mode = 'debug';
        changed = true;
        this.emitUi({ type: 'runtimeAutoTab', tab: 'debug', sessionId: s.id });
      }
    }
    if (changed) this.emitState();
  }

  public getNodeEventHistory(sessionId: string): { events: Array<Extract<RuntimeUiMessage, { type: 'runtimeNodeEvent' }>>; dropped: number } | null {
    const h = this.nodeEventHistory.get(sessionId);
    if (!h) return null;
    return { events: h.events.slice(), dropped: h.dropped };
  }

  public getFlowHistory(
    sessionId: string
  ): { flows: Array<Extract<RuntimeUiMessage, { type: 'runtimeFlow' }>>; dropped: number } | null {
    const h = this.flowHistory.get(sessionId);
    if (!h) return null;
    return { flows: h.flows.slice(), dropped: h.dropped };
  }

  public getProgramLogHistory(
    sessionId: string
  ): { logs: Array<Extract<RuntimeUiMessage, { type: 'runtimeLog' }>>; dropped: number } | null {
    const h = this.programLogHistory.get(sessionId);
    if (!h) return null;
    return { logs: h.logs.slice(), dropped: h.dropped };
  }

  public subscribe(sessionId: string, subscriberId: string): void {
    const s = this.sessions.get(sessionId);
    if (!s) return;
    if (!subscriberId) return;
    if (s.subscribers.has(subscriberId)) return;
    const wasEmpty = s.subscribers.size === 0;
    s.subscribers.add(subscriberId);
    if (wasEmpty) {
      s.subscribed = true;
      s.conn.sendJson({ type: 'SUBSCRIBE' });
      this.emitUi({
        type: 'runtimeTrace',
        ts: Date.now(),
        sessionId,
        dir: 'out',
        messageType: 'SUBSCRIBE'
      });
      this.emitState();
    } else {
      // No state change for the python process, but update UI so it can reflect selection/subscription intent.
      this.emitState();
    }
  }

  public sendHumanResponse(sessionId: string, requestId: string, content: unknown): void {
    const s = this.sessions.get(sessionId);
    if (!s) return;
    if (!requestId) return;
    try {
      s.conn.sendJson({ type: 'INTERACT_RESPONSE', requestId, content });
      this.emitUi({
        type: 'runtimeTrace',
        ts: Date.now(),
        sessionId,
        dir: 'out',
        messageType: 'INTERACT_RESPONSE',
        payload: { requestId }
      });
    } catch (err) {
      this.emitUi({
        type: 'runtimeLog',
        sessionId,
        level: 'error',
        message: `[runtime] failed to send INTERACT_RESPONSE: ${String(err)}`,
        channel: 'system',
        ts: Date.now()
      });
    }
  }

  public unsubscribe(sessionId: string, subscriberId: string): void {
    const s = this.sessions.get(sessionId);
    if (!s) return;
    if (!subscriberId) return;
    if (!s.subscribers.has(subscriberId)) return;
    s.subscribers.delete(subscriberId);
    if (s.subscribers.size === 0 && s.subscribed) {
      s.subscribed = false;
      s.conn.sendJson({ type: 'UNSUBSCRIBE' });
      this.emitUi({
        type: 'runtimeTrace',
        ts: Date.now(),
        sessionId,
        dir: 'out',
        messageType: 'UNSUBSCRIBE'
      });
      this.emitState();
    } else {
      this.emitState();
    }
  }

  public releaseSubscriber(subscriberId: string): void {
    if (!subscriberId) return;
    let changed = false;
    for (const s of this.sessions.values()) {
      if (!s.subscribers.has(subscriberId)) continue;
      s.subscribers.delete(subscriberId);
      changed = true;
      if (s.subscribers.size === 0 && s.subscribed) {
        s.subscribed = false;
        try {
          s.conn.sendJson({ type: 'UNSUBSCRIBE' });
        } catch {
          // ignore
        }
        this.emitUi({
          type: 'runtimeTrace',
          ts: Date.now(),
          sessionId: s.id,
          dir: 'out',
          messageType: 'UNSUBSCRIBE'
        });
      }
    }
    if (changed) this.emitState();
  }

  public dispose(): void {
    for (const s of this.sessions.values()) {
      try {
        s.conn.close();
      } catch {
        // ignore
      }
    }
    this.sessions.clear();
    void this.server.close();
  }

  private stripInternal(s: SessionInternal): VisualizerSession {
    const { conn: _conn, subscribers: _subscribers, ...rest } = s;
    return rest;
  }

  private onConnection(conn: WsConnection): void {
    const now = Date.now();
    const session: SessionInternal = {
      id: conn.id,
      pid: null,
      graphName: null,
      mode: 'unknown',
      connectedAt: now,
      lastSeenAt: now,
      subscribed: false,
      conn,
      subscribers: new Set()
    };
    this.sessions.set(conn.id, session);

    conn.on('text', (text: string) => this.onText(conn, text));
    conn.on('close', () => this.onClose(conn));
    conn.on('error', (err) => {
      this.emitUi({
        type: 'runtimeLog',
        sessionId: conn.id,
        level: 'error',
        message: `[runtime] socket error: ${String(err)}`,
        channel: 'system',
        ts: Date.now()
      });
    });

    this.emitUi({
      type: 'runtimeLog',
      sessionId: conn.id,
      level: 'info',
      message: `[runtime] client connected: ${conn.remoteAddress || 'unknown'}`,
      channel: 'system',
      ts: Date.now()
    });
    this.emitState();
  }

  private onClose(conn: WsConnection): void {
    if (!this.sessions.has(conn.id)) return;
    this.sessions.delete(conn.id);
    this.emitUi({
      type: 'runtimeLog',
      sessionId: conn.id,
      level: 'info',
      message: `[runtime] client disconnected`,
      channel: 'system',
      ts: Date.now()
    });
    this.emitState();
  }

  private onText(conn: WsConnection, text: string): void {
    const session = this.sessions.get(conn.id);
    if (!session) return;
    session.lastSeenAt = Date.now();

    let msg: any;
    try {
      msg = JSON.parse(text);
    } catch {
      return;
    }
    if (!msg || typeof msg !== 'object') return;

    const type = typeof msg.type === 'string' ? msg.type.toUpperCase() : '';
    this.emitTrace(session.id, type, msg);

    if (type === 'HELLO') {
      session.pid = asNumber(msg.pid);
      session.graphName = asString(msg.graphName) || asString(msg.graph_name);
      session.mode = asMode(msg.mode);
      if (session.mode === 'debug' && session.pid !== null) {
        this.debugPids.add(session.pid);
      }
      if (session.pid !== null && this.debugPids.has(session.pid)) {
        session.mode = 'debug';
      }
      this.emitState();

      if (session.mode === 'debug') {
        this.emitUi({ type: 'runtimeAutoTab', tab: 'debug', sessionId: session.id });
      } else if (session.mode === 'run') {
        this.emitUi({ type: 'runtimeAutoTab', tab: 'run', sessionId: session.id });
      }

      return;
    }

    if (type === 'HEARTBEAT') {
      const pid = asNumber(msg.pid);
      const graphName = asString(msg.graphName) || asString(msg.graph_name);
      if (pid !== null) session.pid = pid;
      if (graphName) session.graphName = graphName;
      if (session.mode === 'unknown') session.mode = asMode(msg.mode);
      if (session.mode === 'debug' && session.pid !== null) {
        this.debugPids.add(session.pid);
      }
      if (session.pid !== null && this.debugPids.has(session.pid)) {
        session.mode = 'debug';
      }
      this.emitState();
      return;
    }

    if (type === 'GRAPH') {
      this.emitUi({ type: 'runtimeDebugGraph', sessionId: session.id, graph: msg.graph });
      return;
    }

    if (type === 'LOG') {
      const levelRaw = typeof msg.level === 'string' ? msg.level.toLowerCase() : 'info';
      const level = levelRaw === 'error' ? 'error' : levelRaw === 'warn' ? 'warn' : 'info';
      const message = typeof msg.message === 'string' ? msg.message : '';
      if (message) {
        const ts = asNumber(msg.ts) ?? Date.now();
        const uiMsg: Extract<RuntimeUiMessage, { type: 'runtimeLog' }> = {
          type: 'runtimeLog',
          sessionId: session.id,
          level,
          message,
          channel: 'program',
          ts
        };
        this.recordProgramLog(uiMsg);
        this.emitUi(uiMsg);
      }
      return;
    }

    if (type === 'NODE_EVENT') {
      const evRaw = typeof msg.event === 'string' ? msg.event.toLowerCase() : '';
      const event = evRaw === 'start' || evRaw === 'end' || evRaw === 'error' ? evRaw : null;
      const node = asString(msg.node) || asString(msg.node_name) || asString(msg.nodeName);
      if (!event || !node) return;
      const ts = asNumber(msg.ts) ?? Date.now();
      const runId = asString(msg.runId) || asString(msg.run_id);
      const inputs = msg.inputs ?? msg.input ?? msg.in;
      const outputs = msg.outputs ?? msg.output ?? msg.out;
      const metrics = msg.metrics ?? msg.metric;
      const error = typeof msg.error === 'string' ? msg.error : undefined;
      const uiMsg: Extract<RuntimeUiMessage, { type: 'runtimeNodeEvent' }> = {
        type: 'runtimeNodeEvent',
        sessionId: session.id,
        node,
        event,
        ts,
        runId: runId ?? undefined,
        inputs,
        outputs,
        metrics,
        error
      };
      this.recordNodeEvent(uiMsg);
      this.emitUi(uiMsg);
      return;
    }

    if (type === 'FLOW') {
      const kind = asString(msg.kind) || asString(msg.event) || 'FLOW';
      const ts = asNumber(msg.ts) ?? Date.now();
      const from = asString(msg.from);
      const to = asString(msg.to);
      const node = asString(msg.node);
      const scope = asString(msg.scope);
      const keys = Array.isArray(msg.keys) ? msg.keys.map((k: any) => String(k)) : undefined;
      const keysDetailsRaw = msg.keysDetails;
      const keysDetails =
        keysDetailsRaw && typeof keysDetailsRaw === 'object' && !Array.isArray(keysDetailsRaw)
          ? Object.fromEntries(Object.entries(keysDetailsRaw as any).map(([k, v]) => [String(k), String(v ?? '')]))
          : undefined;
      const uiMsg: Extract<RuntimeUiMessage, { type: 'runtimeFlow' }> = {
        type: 'runtimeFlow',
        sessionId: session.id,
        ts,
        kind,
        from: from ?? undefined,
        to: to ?? undefined,
        node: node ?? undefined,
        scope: scope ?? undefined,
        keys,
        keysDetails,
        message: msg.message,
        values: msg.values,
        changes: msg.changes,
        totalKeys: asNumber(msg.totalKeys) ?? undefined,
        truncated: !!msg.truncated
      };
      this.recordFlow(uiMsg);
      this.emitUi(uiMsg);
      return;
    }

    if (type === 'HISTORY') {
      const rawEvents = Array.isArray(msg.events) ? msg.events : [];
      const dropped = asNumber(msg.dropped) ?? 0;
      const truncated = asNumber(msg.truncated) ?? 0;

      const nodeEvents: Array<{
        node: string;
        event: 'start' | 'end' | 'error';
        ts: number;
        runId?: string;
        inputs?: unknown;
        outputs?: unknown;
        metrics?: unknown;
        error?: string;
      }> = [];
      const flows: Array<
        Omit<Extract<RuntimeUiMessage, { type: 'runtimeFlow' }>, 'type' | 'sessionId'>
      > = [];
      const programLogs: Array<Extract<RuntimeUiMessage, { type: 'runtimeLog' }>> = [];

      for (const ev of rawEvents) {
        if (!ev || typeof ev !== 'object') continue;
        const evType = typeof (ev as any).type === 'string' ? String((ev as any).type).toUpperCase() : '';

        if (evType === 'NODE_EVENT') {
          const evRaw = typeof (ev as any).event === 'string' ? String((ev as any).event).toLowerCase() : '';
          const event = evRaw === 'start' || evRaw === 'end' || evRaw === 'error' ? (evRaw as any) : null;
          const node = asString((ev as any).node) || asString((ev as any).node_name) || asString((ev as any).nodeName);
          if (!event || !node) continue;
          const ts = asNumber((ev as any).ts) ?? Date.now();
          const runId = asString((ev as any).runId) || asString((ev as any).run_id);
          const inputs = (ev as any).inputs ?? (ev as any).input ?? (ev as any).in;
          const outputs = (ev as any).outputs ?? (ev as any).output ?? (ev as any).out;
          const metrics = (ev as any).metrics ?? (ev as any).metric;
          const error = typeof (ev as any).error === 'string' ? (ev as any).error : undefined;
          const uiMsg: Extract<RuntimeUiMessage, { type: 'runtimeNodeEvent' }> = {
            type: 'runtimeNodeEvent',
            sessionId: session.id,
            node,
            event,
            ts,
            runId: runId ?? undefined,
            inputs,
            outputs,
            metrics,
            error
          };
          this.recordNodeEvent(uiMsg);
          nodeEvents.push({ node, event, ts, runId: runId ?? undefined, inputs, outputs, metrics, error });
          continue;
        }

        if (evType === 'FLOW') {
          const kind = asString((ev as any).kind) || asString((ev as any).event) || 'FLOW';
          const ts = asNumber((ev as any).ts) ?? Date.now();
          const from = asString((ev as any).from);
          const to = asString((ev as any).to);
          const node = asString((ev as any).node);
          const scope = asString((ev as any).scope);
          const keys = Array.isArray((ev as any).keys) ? (ev as any).keys.map((k: any) => String(k)) : undefined;
          const keysDetailsRaw = (ev as any).keysDetails;
          const keysDetails =
            keysDetailsRaw && typeof keysDetailsRaw === 'object' && !Array.isArray(keysDetailsRaw)
              ? Object.fromEntries(Object.entries(keysDetailsRaw as any).map(([k, v]) => [String(k), String(v ?? '')]))
              : undefined;
          const uiMsg: Extract<RuntimeUiMessage, { type: 'runtimeFlow' }> = {
            type: 'runtimeFlow',
            sessionId: session.id,
            ts,
            kind,
            from: from ?? undefined,
            to: to ?? undefined,
            node: node ?? undefined,
            scope: scope ?? undefined,
            keys,
            keysDetails,
            message: (ev as any).message,
            values: (ev as any).values,
            changes: (ev as any).changes,
            totalKeys: asNumber((ev as any).totalKeys) ?? undefined,
            truncated: !!(ev as any).truncated
          };
          this.recordFlow(uiMsg);
          flows.push({
            ts,
            kind,
            from: uiMsg.from,
            to: uiMsg.to,
            node: uiMsg.node,
            scope: uiMsg.scope,
            keys: uiMsg.keys,
            keysDetails: uiMsg.keysDetails,
            message: uiMsg.message,
            values: uiMsg.values,
            changes: uiMsg.changes,
            totalKeys: uiMsg.totalKeys,
            truncated: uiMsg.truncated
          });
          continue;
        }

        if (evType === 'LOG') {
          const levelRaw = typeof (ev as any).level === 'string' ? String((ev as any).level).toLowerCase() : 'info';
          const level = levelRaw === 'error' ? 'error' : levelRaw === 'warn' ? 'warn' : 'info';
          const message = typeof (ev as any).message === 'string' ? (ev as any).message : '';
          if (!message) continue;
          const ts = asNumber((ev as any).ts) ?? Date.now();
          const uiMsg: Extract<RuntimeUiMessage, { type: 'runtimeLog' }> = {
            type: 'runtimeLog',
            sessionId: session.id,
            level,
            message,
            channel: 'program',
            ts
          };
          this.recordProgramLog(uiMsg);
          programLogs.push(uiMsg);
          continue;
        }
      }

      if (nodeEvents.length > 0 || dropped > 0 || truncated > 0) {
        this.emitUi({
          type: 'runtimeHistory',
          sessionId: session.id,
          nodeEvents,
          dropped: dropped > 0 ? dropped : undefined,
          truncated: truncated > 0 ? truncated : undefined
        });
      }

      if (flows.length > 0) {
        this.emitUi({ type: 'runtimeFlowHistory', sessionId: session.id, flows });
      }

      if (programLogs.length > 0) {
        for (const l of programLogs) this.emitUi(l);
      }

      if (dropped > 0 || truncated > 0) {
        this.emitUi({
          type: 'runtimeLog',
          sessionId: session.id,
          level: 'warn',
          message: `[runtime] history replay truncated: dropped=${dropped} payloadTruncated=${truncated}`,
          channel: 'system',
          ts: Date.now()
        });
      }
      return;
    }

    if (type === 'INTERACT_REQUEST') {
      const requestId = asString(msg.requestId) || asString(msg.request_id);
      const prompt = asString(msg.prompt) || '';
      if (!requestId || !prompt) return;
      const node = asString(msg.node) || asString(msg.nodeName) || asString(msg.node_name) || undefined;
      const field = asString(msg.field) || undefined;
      const description = asString(msg.description) || undefined;
      const ts = asNumber(msg.ts) ?? Date.now();
      this.emitUi({
        type: 'runtimeHumanRequest',
        sessionId: session.id,
        requestId,
        node,
        field,
        description,
        prompt,
        ts
      });
      return;
    }

    // Visualizer UI commands (best-effort). These are not UI messages; they are handled by the extension host.
    if (type === 'UI_OPEN_FILE') {
      const filePath =
        asString(msg.filePath) ||
        asString(msg.file_path) ||
        asString(msg.path) ||
        asString(msg.file);
      if (!filePath) return;
      const view = asView(msg.view);
      const reveal = typeof msg.reveal === 'boolean' ? msg.reveal : true;
      const preserveFocus = typeof msg.preserveFocus === 'boolean' ? msg.preserveFocus : view === 'vibe';
      const ts = asNumber(msg.ts) ?? Date.now();
      const cmd: VisualizerUiCommand = {
        kind: 'openFile',
        sessionId: session.id,
        filePath,
        view,
        reveal,
        preserveFocus,
        ts
      };
      this.emit('visualizerUiCommand', cmd);
      return;
    }
  }

  private emitState(): void {
    this.emitUi({
      type: 'runtimeState',
      port: this.port,
      sessions: this.getSessionsSnapshot()
    });
  }

  private emitUi(message: RuntimeUiMessage): void {
    this.emit('uiMessage', message);
  }

  private emitTrace(sessionId: string, messageType: string, msg: any): void {
    const ts = Date.now();
    if (!sessionId) return;

    const safeType = messageType || 'UNKNOWN';
    const payload = this.sanitizeTracePayload(safeType, msg);

    this.emitUi({
      type: 'runtimeTrace',
      ts,
      sessionId,
      dir: 'in',
      messageType: safeType,
      payload
    });
  }

  private recordNodeEvent(msg: Extract<RuntimeUiMessage, { type: 'runtimeNodeEvent' }>): void {
    const sessionId = msg.sessionId;
    if (!sessionId) return;
    const entry = this.nodeEventHistory.get(sessionId) || { events: [], dropped: 0 };
    entry.events.push(msg);
    if (entry.events.length > this.nodeEventHistoryMax) {
      const overflow = entry.events.length - this.nodeEventHistoryMax;
      if (overflow > 0) {
        entry.events.splice(0, overflow);
        entry.dropped += overflow;
      }
    }
    this.nodeEventHistory.set(sessionId, entry);
  }

  private recordFlow(msg: Extract<RuntimeUiMessage, { type: 'runtimeFlow' }>): void {
    const sessionId = msg.sessionId;
    if (!sessionId) return;
    const entry = this.flowHistory.get(sessionId) || { flows: [], dropped: 0 };
    entry.flows.push(msg);
    if (entry.flows.length > this.flowHistoryMax) {
      const overflow = entry.flows.length - this.flowHistoryMax;
      if (overflow > 0) {
        entry.flows.splice(0, overflow);
        entry.dropped += overflow;
      }
    }
    this.flowHistory.set(sessionId, entry);
  }

  private recordProgramLog(msg: Extract<RuntimeUiMessage, { type: 'runtimeLog' }>): void {
    const sessionId = msg.sessionId;
    if (!sessionId) return;
    if (msg.channel && msg.channel !== 'program') return;
    const entry = this.programLogHistory.get(sessionId) || { logs: [], dropped: 0 };
    entry.logs.push(msg);
    if (entry.logs.length > this.programLogHistoryMax) {
      const overflow = entry.logs.length - this.programLogHistoryMax;
      if (overflow > 0) {
        entry.logs.splice(0, overflow);
        entry.dropped += overflow;
      }
    }
    this.programLogHistory.set(sessionId, entry);
  }

  private sanitizeTracePayload(messageType: string, msg: any): unknown {
    try {
      const type = messageType.toUpperCase();
      if (type === 'GRAPH') {
        const g = msg?.graph;
        const nodes = Array.isArray(g?.nodes) ? g.nodes.length : Array.isArray(g?.Nodes) ? g.Nodes.length : null;
        const edges = Array.isArray(g?.edges) ? g.edges.length : Array.isArray(g?.Edges) ? g.Edges.length : null;
        return { nodes, edges };
      }
      if (type === 'LOG') {
        return { level: msg?.level, message: msg?.message };
      }
      if (type === 'NODE_EVENT') {
        return { event: msg?.event, node: msg?.node ?? msg?.node_name ?? msg?.nodeName, runId: msg?.runId ?? msg?.run_id };
      }
      if (type === 'FLOW') {
        return { kind: msg?.kind, node: msg?.node, from: msg?.from, to: msg?.to };
      }
      if (type === 'INTERACT_REQUEST') {
        return { requestId: msg?.requestId ?? msg?.request_id, node: msg?.node, field: msg?.field };
      }
      if (type === 'INTERACT_RESPONSE') {
        return { requestId: msg?.requestId ?? msg?.request_id };
      }
      if (type === 'HELLO' || type === 'HEARTBEAT') {
        return { pid: msg?.pid, graphName: msg?.graphName ?? msg?.graph_name, mode: msg?.mode };
      }
      // Generic: keep shallow fields only
      const out: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(msg || {})) {
        if (k === 'graph') continue;
        if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' || v === null) {
          out[k] = v;
        }
      }
      return out;
    } catch {
      return undefined;
    }
  }
}
