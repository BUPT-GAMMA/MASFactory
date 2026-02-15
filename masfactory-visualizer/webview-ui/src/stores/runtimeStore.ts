import { defineStore } from 'pinia';
import { postMessage } from '../bridge/vscode';
import type { GraphData } from '../types/graph';
import type { ExecutionState, NodeExecution } from '../types/runtimeExec';
import type {
  ArchivedSession,
  DebugSessionState,
  HumanChatMessage,
  HumanInteractionRequest,
  VisualizerSession,
  RuntimeFlowEntry,
  RuntimeLogEntry,
  RuntimeMessage,
  RuntimeTraceEntry
} from './runtimeTypes';
import { bestMatchNodeByLocation, normalizeGraph } from './runtimeNormalizeGraph';

export const useRuntimeStore = defineStore('runtime', {
  state: () => ({
    port: null as number | null,
    sessions: [] as VisualizerSession[],
    selectedSessionId: null as string | null,
    selectedRunSessionId: null as string | null,
    debugGraphs: {} as Record<string, unknown>,
    graphs: {} as Record<string, GraphData>,
    execution: {} as Record<string, ExecutionState>,
    debug: {} as Record<string, DebugSessionState>,
    pendingDebugByPid: {} as Record<string, DebugSessionState>,
    archivedSessions: {} as Record<string, ArchivedSession>,
    pinnedSessionIds: [] as string[],
    logs: [] as RuntimeLogEntry[],
    systemLogs: [] as RuntimeLogEntry[],
    traces: [] as RuntimeTraceEntry[],
    flows: [] as RuntimeFlowEntry[],
    humanRequests: {} as Record<string, HumanInteractionRequest[]>,
    humanChats: {} as Record<string, HumanChatMessage[]>
  }),
  getters: {
    debugSessions: (state) => {
      const active = state.sessions.filter((s) => s.mode === 'debug' || !!state.debug[s.id]);
      const activeIds = new Set(active.map((s) => s.id));
      const archived = Object.values(state.archivedSessions || {}).filter(
        (s) => (s.mode === 'debug' || !!state.debug[s.id]) && !activeIds.has(s.id)
      );
      const pinned = new Set(state.pinnedSessionIds || []);
      const byStableRecency = (a: VisualizerSession | ArchivedSession, b: VisualizerSession | ArchivedSession): number => {
        const ap = pinned.has(a.id) ? 1 : 0;
        const bp = pinned.has(b.id) ? 1 : 0;
        if (ap !== bp) return bp - ap;

        const aAlive = activeIds.has(a.id) ? 1 : 0;
        const bAlive = activeIds.has(b.id) ? 1 : 0;
        if (aAlive !== bAlive) return bAlive - aAlive;

        // Stable ordering: do NOT sort by lastSeenAt (it changes frequently and causes UI flicker).
        const aTime = aAlive ? Number(a.connectedAt) || 0 : Number((a as any).endedAt) || 0;
        const bTime = bAlive ? Number(b.connectedAt) || 0 : Number((b as any).endedAt) || 0;
        if (aTime !== bTime) return bTime - aTime;
        return String(a.id).localeCompare(String(b.id));
      };
      return [...active, ...archived].sort(byStableRecency);
    },
    runSessions: (state) => {
      const active = state.sessions.filter((s) => !(s.mode === 'debug' || !!state.debug[s.id]));
      const activeIds = new Set(active.map((s) => s.id));
      const archived = Object.values(state.archivedSessions || {}).filter(
        (s) => !(s.mode === 'debug' || !!state.debug[s.id]) && !activeIds.has(s.id)
      );
      const pinned = new Set(state.pinnedSessionIds || []);
      const byStableRecency = (a: VisualizerSession | ArchivedSession, b: VisualizerSession | ArchivedSession): number => {
        const ap = pinned.has(a.id) ? 1 : 0;
        const bp = pinned.has(b.id) ? 1 : 0;
        if (ap !== bp) return bp - ap;

        const aAlive = activeIds.has(a.id) ? 1 : 0;
        const bAlive = activeIds.has(b.id) ? 1 : 0;
        if (aAlive !== bAlive) return bAlive - aAlive;

        // Stable ordering: do NOT sort by lastSeenAt (it changes frequently and causes UI flicker).
        const aTime = aAlive ? Number(a.connectedAt) || 0 : Number((a as any).endedAt) || 0;
        const bTime = bAlive ? Number(b.connectedAt) || 0 : Number((b as any).endedAt) || 0;
        if (aTime !== bTime) return bTime - aTime;
        return String(a.id).localeCompare(String(b.id));
      };
      return [...active, ...archived].sort(byStableRecency);
    },
    selectedSession: (state) =>
      state.sessions.find((s) => s.id === state.selectedSessionId) ||
      (state.selectedSessionId ? state.archivedSessions[state.selectedSessionId] : null) ||
      null,
    selectedRunSession: (state) =>
      state.sessions.find((s) => s.id === state.selectedRunSessionId) ||
      (state.selectedRunSessionId ? state.archivedSessions[state.selectedRunSessionId] : null) ||
      null,
    isSessionAlive: (state) => (sessionId: string): boolean => {
      const sid = typeof sessionId === 'string' ? sessionId : '';
      return !!sid && state.sessions.some((s) => s.id === sid);
    },
    humanRequestsForSession: (state) => (sessionId: string) => {
      return state.humanRequests[sessionId] || [];
    },
    humanPendingCount: (state) => (sessionId: string): number => {
      const reqs = state.humanRequests[sessionId] || [];
      return reqs.filter((r) => !r.resolved).length;
    },
    humanWaitingNodeIds: (state) => (sessionId: string): string[] => {
      const reqs = state.humanRequests[sessionId] || [];
      const out = new Set<string>();
      for (const r of reqs) {
        if (r && !r.resolved && typeof r.node === 'string' && r.node) out.add(r.node);
      }
      return Array.from(out);
    },
    humanChatForSession: (state) => (sessionId: string): HumanChatMessage[] => {
      return state.humanChats[sessionId] || [];
    }
  },
  actions: {
    pinSession(sessionId: string) {
      if (!sessionId) return;
      if (this.pinnedSessionIds.includes(sessionId)) return;
      this.pinnedSessionIds = [...this.pinnedSessionIds, sessionId];
    },
    unpinSession(sessionId: string) {
      if (!sessionId) return;
      if (!this.pinnedSessionIds.includes(sessionId)) return;
      this.pinnedSessionIds = this.pinnedSessionIds.filter((id) => id !== sessionId);
    },
    setSelectedSession(id: string | null) {
      this.selectedSessionId = id;
    },
    selectDebugSession(sessionId: string) {
      const prev = this.selectedSessionId;
      if (prev && prev !== sessionId) {
        this.unsubscribe(prev);
      }
      this.selectedSessionId = sessionId;
      this.subscribe(sessionId);
    },
    clearDebugSelection() {
      const sessionId = this.selectedSessionId;
      if (sessionId) {
        this.unsubscribe(sessionId);
      }
      this.selectedSessionId = null;
    },
    setSelectedRunSession(id: string | null) {
      this.selectedRunSessionId = id;
    },
    handleRuntimeMessage(msg: RuntimeMessage) {
      if (!msg || typeof msg !== 'object') return;
      switch (msg.type) {
        case 'runtimeState':
          this.port = msg.port ?? null;
          {
            const prevSessions = this.sessions.slice();
            const nextSessions = Array.isArray(msg.sessions) ? msg.sessions : [];
            this.sessions = nextSessions;

            const alive = new Set(nextSessions.map((s) => s.id));

            // Archive sessions that disappeared (process exited / disconnected).
            // Keep them until the user explicitly deletes them.
            const endedAt = Date.now();
            const archivedUpdates: Record<string, ArchivedSession> = {};
            for (const s of prevSessions) {
              if (alive.has(s.id)) continue;
              const existing = this.archivedSessions[s.id];
              if (existing) continue;
              archivedUpdates[s.id] = { ...s, endedAt };
            }
            if (Object.keys(archivedUpdates).length > 0) {
              this.archivedSessions = { ...this.archivedSessions, ...archivedUpdates };
            }

            // Resolve pending debug events by PID once the visualizer session appears.
            for (const s of nextSessions) {
              if (s.pid === null) continue;
              const pending = this.pendingDebugByPid[String(s.pid)];
              if (!pending) continue;
              this.debug = { ...this.debug, [s.id]: pending };
              delete this.pendingDebugByPid[String(s.pid)];
            }
          }
          return;
        case 'runtimeHumanRequest': {
          const sessionId = typeof msg.sessionId === 'string' ? msg.sessionId : '';
          const requestId = typeof msg.requestId === 'string' ? msg.requestId : '';
          const prompt = typeof msg.prompt === 'string' ? msg.prompt : '';
          if (!sessionId || !requestId || !prompt) return;

          // Keep this session available even after disconnect (HITL should be reviewable).
          this.pinSession(sessionId);

          const ts = typeof msg.ts === 'number' && Number.isFinite(msg.ts) ? msg.ts : Date.now();
          const req: HumanInteractionRequest = {
            requestId,
            node: typeof msg.node === 'string' ? msg.node : undefined,
            field: typeof msg.field === 'string' ? msg.field : undefined,
            description: typeof msg.description === 'string' ? msg.description : undefined,
            prompt,
            ts,
            resolved: false
          };

          const existing = this.humanRequests[sessionId] || [];
          if (!existing.some((r) => r.requestId === requestId)) {
            this.humanRequests = {
              ...this.humanRequests,
              [sessionId]: [...existing, req].slice(-200)
            };
          }

          const chats = this.humanChats[sessionId] || [];
          const chatMsg: HumanChatMessage = {
            id: `${ts}:${requestId}:assistant`,
            role: 'assistant',
            ts,
            content: prompt,
            requestId,
            node: req.node,
            field: req.field
          };
          this.humanChats = {
            ...this.humanChats,
            [sessionId]: [...chats, chatMsg].slice(-400)
          };
          return;
        }
        case 'runtimeHistory':
          if (!msg.sessionId) return;
          if (Array.isArray(msg.nodeEvents)) {
            for (const e of msg.nodeEvents) {
              if (!e || typeof e !== 'object') continue;
              if (!e.node || !e.event) continue;
              this.applyNodeEvent({
                type: 'runtimeNodeEvent',
                sessionId: msg.sessionId,
                node: String(e.node),
                event: e.event,
                ts: typeof e.ts === 'number' ? e.ts : Date.now(),
                runId: typeof e.runId === 'string' ? e.runId : undefined,
                inputs: (e as any).inputs,
                outputs: (e as any).outputs,
                metrics: (e as any).metrics,
                error: typeof (e as any).error === 'string' ? (e as any).error : undefined
              });
            }
          }
          if ((msg.dropped ?? 0) > 0 || (msg.truncated ?? 0) > 0) {
            const parts: string[] = [];
            if ((msg.dropped ?? 0) > 0) parts.push(`dropped=${msg.dropped}`);
            if ((msg.truncated ?? 0) > 0) parts.push(`payloadTruncated=${msg.truncated}`);
            this.systemLogs = [
              ...this.systemLogs.slice(-199),
              {
                ts: Date.now(),
                sessionId: msg.sessionId,
                level: 'warn',
                message: `[runtime] history replay truncated: ${parts.join(' ')}`
              }
            ];
          }
          return;
        case 'runtimeDebugStopped':
          this.applyDebugStopped(msg);
          return;
        case 'runtimeDebugContinued':
          this.applyDebugContinued(msg);
          return;
        case 'runtimeDebugGraph':
          this.debugGraphs = { ...this.debugGraphs, [msg.sessionId]: msg.graph };
          {
            const normalized = normalizeGraph(msg.graph);
            if (normalized) {
              this.graphs = { ...this.graphs, [msg.sessionId]: normalized };
            }
          }
          return;
        case 'runtimeNodeEvent':
          this.applyNodeEvent(msg);
          return;
        case 'runtimeLog':
          {
            const ts = typeof msg.ts === 'number' && Number.isFinite(msg.ts) ? msg.ts : Date.now();
            const inferred =
              msg.channel ??
              (typeof msg.message === 'string' &&
              (msg.message.startsWith('[runtime]') || msg.message.startsWith('[debug]'))
                ? 'system'
                : 'program');
            const entry: RuntimeLogEntry = {
              ts,
              sessionId: msg.sessionId,
              level: msg.level,
              message: msg.message
            };
            if (inferred === 'system') {
              this.systemLogs = [...this.systemLogs.slice(-399), entry];
            } else {
              this.logs = [...this.logs.slice(-399), entry];
            }
          }
          return;
        case 'runtimeTrace':
          this.traces = [
            ...this.traces.slice(-499),
            {
              ts: typeof msg.ts === 'number' ? msg.ts : Date.now(),
              sessionId: msg.sessionId,
              dir: msg.dir,
              messageType: msg.messageType,
              payload: msg.payload
            }
          ];
          return;
        case 'runtimeFlow':
          if (!msg.sessionId) return;
          this.flows = [
            ...this.flows.slice(-999),
            {
              sessionId: msg.sessionId,
              ts: typeof msg.ts === 'number' ? msg.ts : Date.now(),
              kind: msg.kind,
              from: msg.from,
              to: msg.to,
              node: msg.node,
              scope: msg.scope,
              keys: msg.keys,
              keysDetails: msg.keysDetails,
              message: msg.message,
              values: msg.values,
              changes: msg.changes,
              totalKeys: msg.totalKeys,
              truncated: msg.truncated
            }
          ];
          return;
        case 'runtimeFlowHistory':
          if (!msg.sessionId) return;
          if (!Array.isArray(msg.flows) || msg.flows.length === 0) return;
          this.flows = [
            ...this.flows.slice(-999),
            ...msg.flows.map((f) => ({
              sessionId: msg.sessionId,
              ts: typeof (f as any).ts === 'number' ? (f as any).ts : Date.now(),
              kind: String((f as any).kind ?? 'FLOW'),
              from: (f as any).from,
              to: (f as any).to,
              node: (f as any).node,
              scope: (f as any).scope,
              keys: (f as any).keys,
              keysDetails: (f as any).keysDetails,
              message: (f as any).message,
              values: (f as any).values,
              changes: (f as any).changes,
              totalKeys: (f as any).totalKeys,
              truncated: (f as any).truncated
            }))
          ];
          return;
        default:
          return;
      }
    },
    applyDebugStopped(msg: Extract<RuntimeMessage, { type: 'runtimeDebugStopped' }>) {
      const pid = typeof msg.pid === 'number' && Number.isFinite(msg.pid) ? msg.pid : null;
      let sessionId =
        typeof msg.sessionId === 'string' && msg.sessionId.trim() ? msg.sessionId : null;

      if (!sessionId && pid !== null) {
        sessionId = this.sessions.find((s) => s.pid === pid)?.id ?? null;
      }

      if (!sessionId) {
        if (pid === null) return;
        const pending: DebugSessionState = {
          paused: true,
          reason: msg.reason || 'stopped',
          description: msg.description,
          threadId: msg.threadId,
          location: msg.location,
          exception: msg.exception,
          ts: typeof msg.ts === 'number' ? msg.ts : Date.now(),
          pausedNodeIds: [],
          exceptionNodeIds: []
        };
        this.pendingDebugByPid = { ...this.pendingDebugByPid, [String(pid)]: pending };
        return;
      }

      let pausedNodeIds: string[] = [];
      const graph = this.graphs[sessionId];
      if (graph && msg.location) {
        const match = bestMatchNodeByLocation(graph, msg.location);
        if (match) pausedNodeIds = [match];
      }
      // Fallback: if we can't map the location to a node (missing schema),
      // highlight all currently running nodes (best-effort).
      if (pausedNodeIds.length === 0) {
        const exec = this.execution[sessionId];
        const runningNodes = exec?.runningNodes || [];
        if (Array.isArray(runningNodes) && runningNodes.length > 0) {
          pausedNodeIds = runningNodes.slice();
        }
      }

      const reasonLower = String(msg.reason || '').toLowerCase();
      const exceptionNodeIds = reasonLower === 'exception' ? pausedNodeIds.slice() : [];

      const next: DebugSessionState = {
        paused: true,
        reason: msg.reason || 'stopped',
        description: msg.description,
        threadId: msg.threadId,
        location: msg.location,
        exception: msg.exception,
        ts: typeof msg.ts === 'number' ? msg.ts : Date.now(),
        pausedNodeIds,
        exceptionNodeIds
      };
      this.debug = { ...this.debug, [sessionId]: next };
    },
    applyDebugContinued(msg: Extract<RuntimeMessage, { type: 'runtimeDebugContinued' }>) {
      const pid = typeof msg.pid === 'number' && Number.isFinite(msg.pid) ? msg.pid : null;
      let sessionId =
        typeof msg.sessionId === 'string' && msg.sessionId.trim() ? msg.sessionId : null;

      if (!sessionId && pid !== null) {
        sessionId = this.sessions.find((s) => s.pid === pid)?.id ?? null;
      }

      if (pid !== null && this.pendingDebugByPid[String(pid)]) {
        delete this.pendingDebugByPid[String(pid)];
      }

      if (!sessionId) return;
      const prev = this.debug[sessionId];
      if (!prev) return;
      this.debug = {
        ...this.debug,
        [sessionId]: {
          ...prev,
          paused: false,
          ts: typeof msg.ts === 'number' ? msg.ts : Date.now(),
          pausedNodeIds: [],
          exceptionNodeIds: [],
          exception: undefined
        }
      };
    },
    applyNodeEvent(msg: Extract<RuntimeMessage, { type: 'runtimeNodeEvent' }>) {
      const sessionId = msg.sessionId;
      const node = msg.node;
      if (!sessionId || !node) return;

      const state: ExecutionState = this.execution[sessionId] || {
        runningNodes: [],
        nodeHistory: {}
      };

      const runningNodes = Array.isArray(state.runningNodes) ? state.runningNodes.slice() : [];
      const ensureRunning = (nodeId: string) => {
        if (!runningNodes.includes(nodeId)) runningNodes.push(nodeId);
      };
      const clearRunning = (nodeId: string) => {
        const idx = runningNodes.indexOf(nodeId);
        if (idx !== -1) runningNodes.splice(idx, 1);
      };

      const history = state.nodeHistory[node] || [];

      const ts = typeof msg.ts === 'number' && Number.isFinite(msg.ts) ? msg.ts : Date.now();
      const runId =
        typeof msg.runId === 'string' && msg.runId.trim()
          ? msg.runId
          : `${ts}-${Math.random().toString(16).slice(2)}`;

      const cap = 50;
      const pushCapped = (run: NodeExecution) => {
        const next = history.length >= cap ? history.slice(history.length - cap + 1) : history.slice();
        next.push(run);
        state.nodeHistory[node] = next;
      };

      if (msg.event === 'start') {
        ensureRunning(node);
        pushCapped({
          runId,
          startedAt: ts,
          status: 'running',
          inputs: msg.inputs
        });
        state.runningNodes = runningNodes;
        this.execution = { ...this.execution, [sessionId]: state };
        return;
      }

      // end/error
      const nextHistory = history.slice();
      const matchIndex =
        typeof msg.runId === 'string' && msg.runId.trim()
          ? nextHistory
              .map((r, idx) => ({ r, idx }))
              .reverse()
              .find((x) => x.r.runId === msg.runId)?.idx ?? -1
          : nextHistory
              .map((r, idx) => ({ r, idx }))
              .reverse()
              .find((x) => x.r.status === 'running' && !x.r.endedAt)?.idx ?? -1;

      if (matchIndex >= 0) {
        const current = nextHistory[matchIndex];
        nextHistory[matchIndex] = {
          ...current,
          endedAt: ts,
          status: msg.event === 'error' ? 'error' : 'ok',
          outputs: msg.outputs,
          metrics: msg.metrics,
          error: msg.event === 'error' ? msg.error : undefined
        };
      } else {
        // If we didn't see a start, still record it as a completed run.
        nextHistory.push({
          runId,
          startedAt: ts,
          endedAt: ts,
          status: msg.event === 'error' ? 'error' : 'ok',
          inputs: msg.inputs,
          outputs: msg.outputs,
          metrics: msg.metrics,
          error: msg.event === 'error' ? msg.error : undefined
        });
      }

      if (nextHistory.length > cap) {
        state.nodeHistory[node] = nextHistory.slice(nextHistory.length - cap);
      } else {
        state.nodeHistory[node] = nextHistory;
      }

      const stillRunning = (state.nodeHistory[node] || []).some(
        (r) => r.status === 'running' && !r.endedAt
      );
      if (stillRunning) ensureRunning(node);
      else clearRunning(node);
      state.runningNodes = runningNodes;
      this.execution = { ...this.execution, [sessionId]: state };
    },
    subscribe(sessionId: string) {
      postMessage({ type: 'runtimeSubscribe', sessionId });
    },
    unsubscribe(sessionId: string) {
      postMessage({ type: 'runtimeUnsubscribe', sessionId });
    },
    openSessionInTab(sessionId: string) {
      postMessage({ type: 'runtimeOpenSession', sessionId });
    },
    selectRunSession(sessionId: string) {
      const prev = this.selectedRunSessionId;
      if (prev && prev !== sessionId) {
        if (this.isSessionAlive(prev)) this.unsubscribe(prev);
      }
      this.selectedRunSessionId = sessionId;
      if (this.isSessionAlive(sessionId)) this.subscribe(sessionId);
    },
    clearRunSelection() {
      const sessionId = this.selectedRunSessionId;
      if (sessionId) {
        if (this.isSessionAlive(sessionId)) this.unsubscribe(sessionId);
      }
      this.selectedRunSessionId = null;
    },
    deleteChatSession(sessionId: string): void {
      const sid = typeof sessionId === 'string' ? sessionId.trim() : '';
      if (!sid) return;
      if (this.humanRequests[sid]) {
        const next = { ...this.humanRequests };
        delete next[sid];
        this.humanRequests = next;
      }
      if (this.humanChats[sid]) {
        const next = { ...this.humanChats };
        delete next[sid];
        this.humanChats = next;
      }
    },
    deleteSession(sessionId: string): void {
      const sid = typeof sessionId === 'string' ? sessionId.trim() : '';
      if (!sid) return;
      // Only allow deleting archived sessions (active sessions will reappear from runtimeState).
      if (this.isSessionAlive(sid)) return;

      if (this.selectedRunSessionId === sid) this.selectedRunSessionId = null;
      if (this.selectedSessionId === sid) this.selectedSessionId = null;
      if (this.pinnedSessionIds.includes(sid)) {
        this.pinnedSessionIds = this.pinnedSessionIds.filter((id) => id !== sid);
      }

      if (this.archivedSessions[sid]) {
        const next = { ...this.archivedSessions };
        delete next[sid];
        this.archivedSessions = next;
      }

      if (this.graphs[sid]) {
        const next = { ...this.graphs };
        delete next[sid];
        this.graphs = next;
      }
      if (this.debugGraphs[sid]) {
        const next = { ...this.debugGraphs };
        delete next[sid];
        this.debugGraphs = next;
      }
      if (this.execution[sid]) {
        const next = { ...this.execution };
        delete next[sid];
        this.execution = next;
      }
      if (this.debug[sid]) {
        const next = { ...this.debug };
        delete next[sid];
        this.debug = next;
      }

      this.deleteChatSession(sid);

      // Best-effort prune global arrays for this session (keeps UI snappy).
      this.logs = this.logs.filter((l) => l.sessionId !== sid);
      this.systemLogs = this.systemLogs.filter((l) => l.sessionId !== sid);
      this.traces = this.traces.filter((t) => t.sessionId !== sid);
      this.flows = this.flows.filter((f) => f.sessionId !== sid);
    },
    respondToNextHumanRequest(sessionId: string, content: string): boolean {
      const sid = typeof sessionId === 'string' ? sessionId : '';
      const text = typeof content === 'string' ? content : String(content ?? '');
      if (!sid) return false;

      const reqs = this.humanRequests[sid] || [];
      const idx = reqs.findIndex((r) => r && !r.resolved);
      if (idx === -1) return false;

      const req = reqs[idx];
      const ts = Date.now();
      const requestId = req.requestId;

      const updatedReqs = reqs.slice();
      updatedReqs[idx] = {
        ...req,
        resolved: true,
        response: text,
        responseTs: ts
      };
      this.humanRequests = { ...this.humanRequests, [sid]: updatedReqs };

      const chats = this.humanChats[sid] || [];
      const chatMsg: HumanChatMessage = {
        id: `${ts}:${requestId}:user`,
        role: 'user',
        ts,
        content: text,
        requestId,
        node: req.node,
        field: req.field
      };
      this.humanChats = { ...this.humanChats, [sid]: [...chats, chatMsg].slice(-400) };

      postMessage({ type: 'runtimeHumanResponse', sessionId: sid, requestId, content: text });
      return true;
    }
  }
});
