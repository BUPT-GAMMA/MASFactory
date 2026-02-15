import type { GraphData, GraphEdge } from '../types/graph';
import type { DebugLocation } from './runtimeTypes';

function normalizeFsPath(p: string): string {
  return String(p || '')
    .replace(/\\/g, '/')
    .replace(/\/+/g, '/');
}

export function bestMatchNodeByLocation(graph: GraphData, location: DebugLocation): string | null {
  const file = typeof location.path === 'string' ? location.path : '';
  const line = typeof location.line === 'number' && Number.isFinite(location.line) ? location.line : null;
  if (!file || line === null) return null;

  const nodeFilePaths = graph.nodeFilePaths || {};
  const nodeLineNumbers = graph.nodeLineNumbers || {};
  const targetFile = normalizeFsPath(file);

  let bestId: string | null = null;
  let bestLine = -1;

  for (const [nodeId, fp] of Object.entries(nodeFilePaths)) {
    if (!fp) continue;
    if (normalizeFsPath(fp) !== targetFile) continue;
    const ln = nodeLineNumbers[nodeId];
    if (typeof ln !== 'number' || !Number.isFinite(ln)) continue;
    if (ln <= line && ln > bestLine) {
      bestLine = ln;
      bestId = nodeId;
    }
  }

  if (bestId) return bestId;

  // Fallback: closest line in the same file.
  let closestId: string | null = null;
  let closestDist = Number.POSITIVE_INFINITY;
  for (const [nodeId, fp] of Object.entries(nodeFilePaths)) {
    if (!fp) continue;
    if (normalizeFsPath(fp) !== targetFile) continue;
    const ln = nodeLineNumbers[nodeId];
    if (typeof ln !== 'number' || !Number.isFinite(ln)) continue;
    const dist = Math.abs(ln - line);
    if (dist < closestDist) {
      closestDist = dist;
      closestId = nodeId;
    }
  }
  return closestId;
}

export function normalizeGraph(graph: unknown): GraphData | null {
  if (!graph || typeof graph !== 'object') return null;
  const g: any = graph as any;

  const normalizeStringMap = (raw: unknown): Record<string, string> => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(raw as any)) {
      out[String(k)] = v === undefined || v === null ? '' : String(v);
    }
    return out;
  };

  const normalizeNodeKeySemantics = (
    raw: unknown
  ): Record<string, unknown> | null | 'empty' | undefined => {
    if (raw === undefined) return undefined;
    if (raw === null) return null;
    if (raw === 'empty') return 'empty';
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(raw as any)) {
      out[String(k)] = v;
    }
    return Object.keys(out).length === 0 ? 'empty' : out;
  };

  const normalizeNodeMap = <T>(
    raw: unknown,
    mapFn: (value: unknown) => T | undefined
  ): Record<string, T> | undefined => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined;
    const out: Record<string, T> = {};
    for (const [k, v] of Object.entries(raw as any)) {
      const mapped = mapFn(v);
      if (mapped !== undefined) out[String(k)] = mapped;
    }
    return Object.keys(out).length > 0 ? out : undefined;
  };

  // GraphData-ish shape
  if (Array.isArray(g.nodes) && Array.isArray(g.edges)) {
    const nodes = g.nodes.map((n: any) => String(n));
    const edges: GraphEdge[] = g.edges
      .map((e: any) => {
        if (!e || typeof e !== 'object') return null;
        const from = typeof e.from === 'string' ? e.from : null;
        const to = typeof e.to === 'string' ? e.to : null;
        if (!from || !to) return null;
        const out: GraphEdge = { from, to };
        if (typeof e.label === 'string') out.label = e.label;
        if (Array.isArray(e.keys)) out.keys = e.keys.map((k: any) => String(k));
        if (typeof e.lineNumber === 'number' && Number.isFinite(e.lineNumber)) out.lineNumber = e.lineNumber;
        if (typeof e.filePath === 'string') out.filePath = e.filePath;
        if (typeof e.variableName === 'string') out.variableName = e.variableName;
        if (e.keysDetails && typeof e.keysDetails === 'object') {
          const details: Record<string, string> = {};
          for (const [k, v] of Object.entries(e.keysDetails)) {
            details[String(k)] = v === undefined || v === null ? '' : String(v);
          }
          out.keysDetails = details;
        }
        return out;
      })
      .filter(Boolean) as GraphEdge[];

    // Ensure all edge endpoints exist in node list.
    const nodeSet = new Set(nodes);
    for (const e of edges) {
      nodeSet.add(e.from);
      nodeSet.add(e.to);
    }

    const nodeLineNumbers = normalizeNodeMap<number>(g.nodeLineNumbers, (v) =>
      typeof v === 'number' && Number.isFinite(v) ? v : undefined
    );
    const nodeFilePaths = normalizeNodeMap<string>(g.nodeFilePaths, (v) =>
      typeof v === 'string' && v ? v : undefined
    );
    const nodePullKeys = normalizeNodeMap<Record<string, unknown> | null | 'empty'>(g.nodePullKeys, (v) =>
      normalizeNodeKeySemantics(v)
    );
    const nodePushKeys = normalizeNodeMap<Record<string, unknown> | null | 'empty'>(g.nodePushKeys, (v) =>
      normalizeNodeKeySemantics(v)
    );
    const nodeAttributes = normalizeNodeMap<Record<string, unknown> | null>(g.nodeAttributes, (v) => {
      if (v === null) return null;
      if (!v || typeof v !== 'object' || Array.isArray(v)) return undefined;
      const out: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(v as any)) out[String(k)] = val;
      return out;
    });
    const nodeInputKeys = normalizeNodeMap<Record<string, unknown>>(g.nodeInputKeys, (v) => {
      if (!v || typeof v !== 'object' || Array.isArray(v)) return undefined;
      const out: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(v as any)) out[String(k)] = val;
      return Object.keys(out).length > 0 ? out : undefined;
    });
    const nodeOutputKeys = normalizeNodeMap<Record<string, unknown>>(g.nodeOutputKeys, (v) => {
      if (!v || typeof v !== 'object' || Array.isArray(v)) return undefined;
      const out: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(v as any)) out[String(k)] = val;
      return Object.keys(out).length > 0 ? out : undefined;
    });
    const nodeInstructions = normalizeNodeMap<string>(g.nodeInstructions, (v) =>
      typeof v === 'string' && v.trim() ? v : undefined
    );
    const nodePromptTemplates = normalizeNodeMap<string>(g.nodePromptTemplates, (v) =>
      typeof v === 'string' && v.trim() ? v : undefined
    );
    const nodeAliases = normalizeNodeMap<string[]>(g.nodeAliases, (v) =>
      Array.isArray(v) ? v.map((x) => String(x)) : undefined
    );
    const graphAttributesSummary =
      g.graphAttributesSummary && typeof g.graphAttributesSummary === 'object' && !Array.isArray(g.graphAttributesSummary)
        ? (g.graphAttributesSummary as any)
        : undefined;

    return {
      nodes: Array.from(nodeSet),
      nodeTypes: g.nodeTypes && typeof g.nodeTypes === 'object' ? g.nodeTypes : {},
      edges,
      subgraphs: g.subgraphs && typeof g.subgraphs === 'object' ? g.subgraphs : {},
      subgraphTypes: g.subgraphTypes && typeof g.subgraphTypes === 'object' ? g.subgraphTypes : {},
      subgraphParents:
        g.subgraphParents && typeof g.subgraphParents === 'object' ? g.subgraphParents : {},
      nodeLineNumbers,
      nodeFilePaths,
      nodePullKeys,
      nodePushKeys,
      nodeAttributes,
      nodeInputKeys,
      nodeOutputKeys,
      nodeInstructions,
      nodePromptTemplates,
      nodeAliases,
      graphAttributesSummary
    };
  }

  // Graph design JSON shape: { Nodes: [...], Edges: [...] }
  if (Array.isArray(g.Nodes) && Array.isArray(g.Edges)) {
    const nodes: string[] = [];
    const nodeTypes: Record<string, string> = {};
    const nodeInputKeys: Record<string, Record<string, unknown>> = {};
    const nodeOutputKeys: Record<string, Record<string, unknown>> = {};
    const nodePullKeys: Record<string, Record<string, unknown> | null | 'empty'> = {};
    const nodePushKeys: Record<string, Record<string, unknown> | null | 'empty'> = {};
    const nodeAttributes: Record<string, Record<string, unknown> | null> = {};
    const nodeInstructions: Record<string, string> = {};
    const nodePromptTemplates: Record<string, string> = {};

    const pickString = (value: unknown): string | undefined =>
      typeof value === 'string' && value.trim() ? value : undefined;

    for (const n of g.Nodes) {
      if (typeof n === 'string') {
        nodes.push(n);
        continue;
      }
      if (n && typeof n === 'object') {
        const name = typeof (n as any).name === 'string' ? (n as any).name : null;
        if (!name) continue;
        nodes.push(name);
        const typ = typeof (n as any).type === 'string' ? (n as any).type : null;
        if (typ) nodeTypes[name] = typ;

        const inputKeys = (n as any).input_keys ?? (n as any).inputKeys;
        const outputKeys = (n as any).output_keys ?? (n as any).outputKeys;
        const pullKeysRaw = (n as any).pull_keys ?? (n as any).pullKeys;
        const pushKeysRaw = (n as any).push_keys ?? (n as any).pushKeys;
        const instructions = pickString((n as any).instructions ?? (n as any).prompt);
        const promptTemplate = pickString((n as any).prompt_template ?? (n as any).promptTemplate);
        const attrs = (n as any).attributes;

        const normalizedInput = normalizeStringMap(inputKeys);
        const normalizedOutput = normalizeStringMap(outputKeys);
        if (Object.keys(normalizedInput).length > 0) nodeInputKeys[name] = normalizedInput;
        if (Object.keys(normalizedOutput).length > 0) nodeOutputKeys[name] = normalizedOutput;

        const pullSem = normalizeNodeKeySemantics(pullKeysRaw);
        const pushSem = normalizeNodeKeySemantics(pushKeysRaw);
        if (pullSem !== undefined) nodePullKeys[name] = pullSem;
        if (pushSem !== undefined) nodePushKeys[name] = pushSem;

        if (instructions) nodeInstructions[name] = instructions;
        if (promptTemplate) nodePromptTemplates[name] = promptTemplate;
        if (attrs && typeof attrs === 'object' && !Array.isArray(attrs)) {
          const out: Record<string, unknown> = {};
          for (const [k, v] of Object.entries(attrs as any)) out[String(k)] = v;
          nodeAttributes[name] = out;
        }
      }
    }

    const edges: GraphEdge[] = [];
    for (const e of g.Edges) {
      if (!e || typeof e !== 'object') continue;
      const from = typeof (e as any).from === 'string' ? (e as any).from : null;
      const to = typeof (e as any).to === 'string' ? (e as any).to : null;
      if (!from || !to) continue;
      const out: GraphEdge = { from, to };
      if (typeof (e as any).label === 'string') out.label = (e as any).label;
      const keys = (e as any).keys;
      if (Array.isArray(keys)) out.keys = keys.map((k: any) => String(k));
      if (keys && typeof keys === 'object' && !Array.isArray(keys)) {
        const details: Record<string, string> = {};
        for (const [k, v] of Object.entries(keys)) {
          details[String(k)] = v === undefined || v === null ? '' : String(v);
        }
        out.keysDetails = details;
        out.keys = Object.keys(details);
      }
      edges.push(out);
    }

    const nodeSet = new Set(nodes);
    for (const e of edges) {
      nodeSet.add(e.from);
      nodeSet.add(e.to);
    }

    return {
      nodes: Array.from(nodeSet),
      nodeTypes,
      edges,
      subgraphs: {},
      subgraphTypes: {},
      subgraphParents: {},
      nodeInputKeys: Object.keys(nodeInputKeys).length > 0 ? nodeInputKeys : undefined,
      nodeOutputKeys: Object.keys(nodeOutputKeys).length > 0 ? nodeOutputKeys : undefined,
      nodePullKeys: Object.keys(nodePullKeys).length > 0 ? nodePullKeys : undefined,
      nodePushKeys: Object.keys(nodePushKeys).length > 0 ? nodePushKeys : undefined,
      nodeAttributes: Object.keys(nodeAttributes).length > 0 ? nodeAttributes : undefined,
      nodeInstructions: Object.keys(nodeInstructions).length > 0 ? nodeInstructions : undefined,
      nodePromptTemplates:
        Object.keys(nodePromptTemplates).length > 0 ? nodePromptTemplates : undefined
    };
  }

  return null;
}

