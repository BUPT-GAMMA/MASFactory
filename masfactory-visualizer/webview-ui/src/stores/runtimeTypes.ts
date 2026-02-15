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

export interface DebugSessionState {
  paused: boolean;
  reason: string;
  description?: string;
  threadId?: number;
  location?: DebugLocation;
  exception?: DebugExceptionInfo;
  ts: number;
  pausedNodeIds: string[];
  exceptionNodeIds: string[];
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

export interface ArchivedSession extends VisualizerSession {
  endedAt: number;
}

export interface RuntimeLogEntry {
  ts: number;
  sessionId?: string;
  level: 'info' | 'warn' | 'error';
  message: string;
}

export interface RuntimeTraceEntry {
  ts: number;
  sessionId: string;
  dir: 'in' | 'out';
  messageType: string;
  payload?: unknown;
}

export interface RuntimeFlowEntry {
  ts: number;
  sessionId: string;
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

export interface HumanInteractionRequest {
  requestId: string;
  node?: string;
  field?: string;
  description?: string;
  prompt: string;
  ts: number;
  resolved?: boolean;
  response?: string;
  responseTs?: number;
}

export interface HumanChatMessage {
  id: string;
  role: 'assistant' | 'user';
  ts: number;
  content: string;
  requestId?: string;
  node?: string;
  field?: string;
}

export type RuntimeMessage =
  | { type: 'runtimeState'; port: number | null; sessions: VisualizerSession[] }
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
  | { type: 'runtimeAutoTab'; tab: 'debug' | 'run'; sessionId: string }
  | { type: 'runtimeDebugGraph'; sessionId: string; graph: unknown }
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
  | { type: 'runtimeFlowHistory'; sessionId: string; flows: Array<Omit<RuntimeFlowEntry, 'sessionId'>> }
  | {
      type: 'runtimeTrace';
      sessionId: string;
      dir: 'in' | 'out';
      messageType: string;
      payload?: unknown;
      ts: number;
    };

