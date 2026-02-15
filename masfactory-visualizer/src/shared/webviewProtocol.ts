import { assertSupportedInboundProtocol } from './protocolVersion';
import type { RuntimeUiMessage } from './runtimeProtocol';
import { parseRuntimeMessage } from './runtimeProtocol';

export type VibeDocumentMessage = {
  type: 'vibeDocument';
  documentUri: string;
  fileName: string;
  text: string;
  languageId?: string;
};

export type VibeSaveResultMessage = {
  type: 'vibeSaveResult';
  documentUri: string;
  ok: boolean;
  error?: string | null;
};

export type PreviewUpdateMessage<TGraphData = unknown> = {
  type: 'update';
  protocolVersion?: number;
  data: TGraphData;
  settings?: unknown;
  documentUri: string;
  conditionVariables?: string[];
  loopControls?: Record<string, unknown>;
  loopWarnings?: string[];
  loopIterations?: Record<string, number>;
  adjacencyGraphControls?: Record<string, unknown>;
};

export type PreviewClearMessage = { type: 'clear'; protocolVersion?: number; reason?: string };

export type UiSetActiveTabMessage = {
  type: 'uiSetActiveTab';
  tab: 'preview' | 'debug' | 'run' | 'vibe';
};

export type AppInboundMessage<TGraphData = unknown> =
  | VibeDocumentMessage
  | VibeSaveResultMessage
  | PreviewUpdateMessage<TGraphData>
  | PreviewClearMessage
  | UiSetActiveTabMessage
  | RuntimeUiMessage;

export type NavigateToLineMessage = { type: 'navigateToLine'; uri: string; lineNumber: number };
export type ConditionChangedMessage = {
  type: 'conditionChanged';
  documentUri?: string;
  conditions: Record<string, boolean>;
};
export type LoopIterationsChangedMessage = {
  type: 'loopIterationsChanged';
  documentUri?: string;
  loopIterations: Record<string, number>;
  conditions?: Record<string, boolean>;
};
export type AdjacencyGraphChangedMessage = {
  type: 'adjacencyGraphChanged';
  documentUri?: string;
  graphVariable: string;
  edges: Array<{ from: number; to: number; keys?: Record<string, string> }>;
  conditions?: Record<string, boolean>;
  loopIterations?: Record<string, number>;
};
export type RefreshGraphMessage = { type: 'refreshGraph'; documentUri?: string };
export type ResetViewStateMessage = { type: 'resetViewState'; documentUri?: string };
export type TemplateSelectionChangedMessage = {
  type: 'templateSelectionChanged';
  documentUri?: string;
  templateName: string | null;
};
export type WebviewReadyMessage = { type: 'webviewReady' };
export type RuntimeWebviewReadyMessage = { type: 'runtimeWebviewReady' };
export type RuntimeSubscribeMessage = { type: 'runtimeSubscribe'; sessionId: string };
export type RuntimeUnsubscribeMessage = { type: 'runtimeUnsubscribe'; sessionId: string };
export type RuntimeOpenSessionMessage = { type: 'runtimeOpenSession'; sessionId: string };
export type RuntimeHumanResponseMessage = {
  type: 'runtimeHumanResponse';
  sessionId: string;
  requestId: string;
  content: string;
};
export type OpenFileLocationMessage = { type: 'openFileLocation'; filePath: string; line?: number; column?: number };
export type VibeSaveMessage = { type: 'vibeSave'; documentUri: string; text: string };
export type VibeReloadMessage = { type: 'vibeReload'; documentUri: string };

export type WebviewOutboundMessage =
  | NavigateToLineMessage
  | ConditionChangedMessage
  | LoopIterationsChangedMessage
  | AdjacencyGraphChangedMessage
  | TemplateSelectionChangedMessage
  | RefreshGraphMessage
  | ResetViewStateMessage
  | WebviewReadyMessage
  | RuntimeWebviewReadyMessage
  | RuntimeSubscribeMessage
  | RuntimeUnsubscribeMessage
  | RuntimeOpenSessionMessage
  | RuntimeHumanResponseMessage
  | OpenFileLocationMessage
  | VibeSaveMessage
  | VibeReloadMessage;

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function asBoolean(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asOptionalString(value: unknown): string | undefined {
  const s = asString(value);
  return s ?? undefined;
}

function parseBoolRecord(value: unknown): Record<string, boolean> {
  if (!isRecord(value)) return {};
  const out: Record<string, boolean> = {};
  for (const [k, v] of Object.entries(value)) {
    if (typeof v === 'boolean') out[String(k)] = v;
  }
  return out;
}

function parseNumberRecord(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {};
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(value)) {
    const n = typeof v === 'number' ? v : Number(v);
    if (Number.isFinite(n)) out[String(k)] = n;
  }
  return out;
}

function parseEdges(value: unknown): Array<{ from: number; to: number; keys?: Record<string, string> }> {
  if (!Array.isArray(value)) return [];
  const out: Array<{ from: number; to: number; keys?: Record<string, string> }> = [];
  for (const item of value) {
    if (!isRecord(item)) continue;
    const from = asFiniteNumber(item.from);
    const to = asFiniteNumber(item.to);
    if (from === null || to === null) continue;
    const edge: { from: number; to: number; keys?: Record<string, string> } = { from, to };
    if (isRecord(item.keys)) {
      const keys: Record<string, string> = {};
      for (const [k, v] of Object.entries(item.keys)) keys[String(k)] = v === undefined || v === null ? '' : String(v);
      if (Object.keys(keys).length > 0) edge.keys = keys;
    }
    out.push(edge);
  }
  return out;
}

export function parseWebviewOutboundMessage(raw: unknown): WebviewOutboundMessage | null {
  if (!isRecord(raw)) return null;
  const type = asString(raw.type);
  if (!type) return null;

  if (type === 'navigateToLine') {
    const uri = asString(raw.uri);
    const lineNumber = asFiniteNumber(raw.lineNumber);
    if (!uri || lineNumber === null) return null;
    return { type, uri, lineNumber: Math.floor(lineNumber) };
  }

  if (type === 'conditionChanged') {
    const conditions = parseBoolRecord(raw.conditions);
    return { type, documentUri: asOptionalString(raw.documentUri), conditions };
  }

  if (type === 'loopIterationsChanged') {
    const loopIterations = parseNumberRecord(raw.loopIterations);
    const conditions = isRecord(raw.conditions) ? parseBoolRecord(raw.conditions) : undefined;
    return { type, documentUri: asOptionalString(raw.documentUri), loopIterations, conditions };
  }

  if (type === 'adjacencyGraphChanged') {
    const graphVariable = asString(raw.graphVariable);
    const edges = parseEdges(raw.edges);
    if (!graphVariable) return null;
    const conditions = isRecord(raw.conditions) ? parseBoolRecord(raw.conditions) : undefined;
    const loopIterations = isRecord(raw.loopIterations) ? parseNumberRecord(raw.loopIterations) : undefined;
    return { type, documentUri: asOptionalString(raw.documentUri), graphVariable, edges, conditions, loopIterations };
  }

  if (type === 'templateSelectionChanged') {
    const templateNameRaw = raw.templateName;
    const templateName =
      typeof templateNameRaw === 'string' ? templateNameRaw.trim() : templateNameRaw === null ? null : '';
    if (templateNameRaw !== null && typeof templateNameRaw !== 'string') return null;
    return {
      type,
      documentUri: asOptionalString(raw.documentUri),
      templateName: templateName ? templateName : null
    };
  }

  if (type === 'refreshGraph') return { type, documentUri: asOptionalString(raw.documentUri) };
  if (type === 'resetViewState') return { type, documentUri: asOptionalString(raw.documentUri) };

  if (type === 'webviewReady') return { type };
  if (type === 'runtimeWebviewReady') return { type };

  if (type === 'runtimeSubscribe' || type === 'runtimeUnsubscribe' || type === 'runtimeOpenSession') {
    const sessionId = asString(raw.sessionId);
    if (!sessionId) return null;
    return { type, sessionId } as any;
  }

  if (type === 'runtimeHumanResponse') {
    const sessionId = asString(raw.sessionId);
    const requestId = asString(raw.requestId);
    const content = typeof raw.content === 'string' ? raw.content : '';
    if (!sessionId || !requestId) return null;
    return { type, sessionId, requestId, content };
  }

  if (type === 'openFileLocation') {
    const filePath = asString(raw.filePath);
    if (!filePath) return null;
    const line = asFiniteNumber(raw.line);
    const column = asFiniteNumber(raw.column);
    return {
      type,
      filePath,
      line: line === null ? undefined : Math.floor(line),
      column: column === null ? undefined : Math.floor(column)
    };
  }

  if (type === 'vibeSave') {
    const documentUri = asString(raw.documentUri);
    if (!documentUri) return null;
    if (typeof raw.text !== 'string') return null;
    return { type, documentUri, text: raw.text };
  }

  if (type === 'vibeReload') {
    const documentUri = asString(raw.documentUri);
    if (!documentUri) return null;
    return { type, documentUri };
  }

  return null;
}

function parseGraphData(value: unknown): unknown | null {
  if (!isRecord(value)) return null;
  const nodes = Array.isArray(value.nodes) ? value.nodes.filter((x) => typeof x === 'string' && x) : null;
  const edges = Array.isArray(value.edges) ? value.edges.filter((e) => isRecord(e)) : null;
  if (!nodes || !edges) return null;
  return value;
}

export function parseAppInboundMessage<TGraphData = unknown>(data: unknown): AppInboundMessage<TGraphData> | null {
  if (!isRecord(data)) return null;
  assertSupportedInboundProtocol(data);
  const type = asString(data.type);
  if (!type) return null;

  if (type === 'uiSetActiveTab') {
    const tab = asString((data as any).tab);
    if (tab !== 'preview' && tab !== 'debug' && tab !== 'run' && tab !== 'vibe') return null;
    return { type, tab };
  }

  if (type === 'vibeDocument') {
    const documentUri = asString(data.documentUri) ?? '';
    const fileName = asString(data.fileName) ?? '';
    const text = typeof data.text === 'string' ? data.text : null;
    const languageId = typeof data.languageId === 'string' ? data.languageId : undefined;
    if (!documentUri || !fileName || text === null) return null;
    return { type, documentUri, fileName, text, languageId };
  }

  if (type === 'vibeSaveResult') {
    const documentUri = asString(data.documentUri) ?? '';
    const ok = asBoolean(data.ok);
    const error = typeof data.error === 'string' ? data.error : null;
    if (!documentUri || ok === null) return null;
    return { type, documentUri, ok, error };
  }

  if (type === 'clear') {
    const reason = typeof data.reason === 'string' ? data.reason : undefined;
    const protocolVersion = asFiniteNumber((data as any).protocolVersion) ?? undefined;
    return { type, reason, protocolVersion };
  }

  if (type === 'update') {
    const documentUri = asString(data.documentUri) ?? '';
    const graph = parseGraphData(data.data);
    if (!documentUri || !graph) return null;
    const protocolVersion = asFiniteNumber((data as any).protocolVersion) ?? undefined;
    const conditionVariables = Array.isArray(data.conditionVariables)
      ? data.conditionVariables.filter((x) => typeof x === 'string' && x)
      : undefined;
    const loopWarnings = Array.isArray(data.loopWarnings)
      ? data.loopWarnings.filter((x) => typeof x === 'string')
      : undefined;
    const loopIterations = isRecord(data.loopIterations) ? (data.loopIterations as Record<string, number>) : undefined;
    return {
      type,
      protocolVersion,
      data: graph as any as TGraphData,
      settings: isRecord(data.settings) ? (data.settings as unknown) : undefined,
      documentUri,
      conditionVariables,
      loopControls: isRecord(data.loopControls) ? (data.loopControls as Record<string, unknown>) : undefined,
      loopWarnings,
      loopIterations,
      adjacencyGraphControls: isRecord(data.adjacencyGraphControls)
        ? (data.adjacencyGraphControls as Record<string, unknown>)
        : undefined
    };
  }

  if (type.startsWith('runtime')) {
    return parseRuntimeMessage(data);
  }

  return null;
}
