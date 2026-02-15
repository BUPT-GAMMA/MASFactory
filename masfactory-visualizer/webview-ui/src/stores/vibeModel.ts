import type { VibeEdgeSpec, VibeGraphDesign, VibeGraphLocator, VibeLayout, VibeNodeSpec, VibeNodeType } from './vibeTypes';
import { fromV4GraphDesign, isV4Graph, type VibeV4Graph } from '../utils/vibeGraphDesignV4.js';

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function keysListToDict(keys: unknown): Record<string, string> {
  if (isRecord(keys)) {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(keys)) {
      out[String(k)] = v == null ? '' : typeof v === 'string' ? v : JSON.stringify(v);
    }
    return out;
  }
  if (Array.isArray(keys)) {
    const out: Record<string, string> = {};
    for (const k of keys) out[String(k)] = '';
    return out;
  }
  return {};
}

function normalizeKeysField(keys: unknown): Record<string, string> | null | undefined {
  if (keys === undefined) return undefined;
  if (keys === null) return null;
  return keysListToDict(keys);
}

export function normalizeGraphDesign(raw: VibeGraphDesign): VibeGraphDesign {
  const nodes = Array.isArray(raw.Nodes) ? raw.Nodes : [];
  const edges = Array.isArray(raw.Edges) ? raw.Edges : [];

  const normNodes: VibeNodeSpec[] = nodes
    .filter((n) => !!n && typeof n === 'object')
    .map((n) => {
      const spec = n as VibeNodeSpec;
      const parent = typeof spec.parent === 'string' ? spec.parent.trim() : '';
      const hasInputFields = Object.prototype.hasOwnProperty.call(spec as any, 'input_fields');
      const hasOutputFields = Object.prototype.hasOwnProperty.call(spec as any, 'output_fields');
      const hasPullKeys = Object.prototype.hasOwnProperty.call(spec as any, 'pull_keys');
      const hasPushKeys = Object.prototype.hasOwnProperty.call(spec as any, 'push_keys');
      const hasLegacyTools = Object.prototype.hasOwnProperty.call(spec as any, 'tools_allowed');
      const hasTools = Object.prototype.hasOwnProperty.call(spec as any, 'tools') || hasLegacyTools;
      const hasLegacyTerminate = Object.prototype.hasOwnProperty.call(spec as any, 'terminate_condition');
      const hasTerminatePrompt =
        Object.prototype.hasOwnProperty.call(spec as any, 'terminate_condition_prompt') || hasLegacyTerminate;

      const pull = hasPullKeys ? (spec as any).pull_keys : hasInputFields ? (spec as any).input_fields : undefined;
      const push = hasPushKeys ? (spec as any).push_keys : hasOutputFields ? (spec as any).output_fields : undefined;
      const prompt = (spec as any).prompt;
      const label = typeof (spec as any).label === 'string' ? (spec as any).label.trim() : '';
      const agent = typeof (spec as any).agent === 'string' ? (spec as any).agent.trim() : '';
      const instructions =
        spec.instructions === undefined || spec.instructions === null
          ? prompt !== undefined
            ? prompt
            : spec.instructions
          : spec.instructions;
      const terminate_condition_prompt =
        (spec as any).terminate_condition_prompt !== undefined
          ? (spec as any).terminate_condition_prompt
          : (spec as any).terminate_condition;
      const tools = (spec as any).tools !== undefined ? (spec as any).tools : (spec as any).tools_allowed;
      return {
        ...spec,
        type: (spec.type as string) || 'Agent',
        label: label || undefined,
        agent: agent || undefined,
        parent: parent ? parent : undefined,
        // Preserve original field presence to avoid injecting optional fields on save.
        __gd_has_input_fields: hasInputFields,
        __gd_has_output_fields: hasOutputFields,
        __gd_has_pull_keys: hasPullKeys,
        __gd_has_push_keys: hasPushKeys,
        __gd_has_tools: hasTools,
        __gd_has_terminate_prompt: hasTerminatePrompt,
        __gd_pull_derived: !hasPullKeys && hasInputFields,
        __gd_push_derived: !hasPushKeys && hasOutputFields,
        instructions,
        terminate_condition_prompt,
        tools,
        pull_keys: normalizeKeysField(pull),
        push_keys: normalizeKeysField(push)
      };
    });

  const normEdges = edges
    .filter((e) => !!e && typeof e === 'object')
    .map((e) => {
      const spec = e as any;
      const hasKeys = Object.prototype.hasOwnProperty.call(spec, 'keys') || Object.prototype.hasOwnProperty.call(spec, 'key');
      const keys = Object.prototype.hasOwnProperty.call(spec, 'keys') ? spec.keys : spec.key;
      return {
        ...spec,
        from: String(spec.from ?? ''),
        to: String(spec.to ?? ''),
        // Preserve original field presence to avoid injecting optional fields on save.
        __gd_has_keys: hasKeys,
        keys: normalizeKeysField(keys)
      };
    })
    .filter((e) => !!e.from && !!e.to);

  return { ...raw, Nodes: normNodes, Edges: normEdges };
}

export function safeJsonParse(text: string): { value: unknown; error: string | null } {
  try {
    return { value: JSON.parse(text), error: null };
  } catch (err) {
    return { value: null, error: err instanceof Error ? err.message : String(err) };
  }
}

export function deepClone<T>(v: T): T {
  try {
    return JSON.parse(JSON.stringify(v)) as T;
  } catch {
    return v;
  }
}

function tryParseV4GraphString(text: string): { graph: VibeV4Graph; asString: boolean } | null {
  const trimmed = String(text || '').trim();
  if (!trimmed) return null;
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[') && !trimmed.startsWith('"')) return null;
  const parsed = safeJsonParse(trimmed);
  if (parsed.error) return null;
  if (typeof parsed.value === 'string') {
    const inner = tryParseV4GraphString(parsed.value);
    if (!inner) return null;
    return { graph: inner.graph, asString: true };
  }
  if (isV4Graph(parsed.value)) return { graph: parsed.value, asString: false };
  if (isRecord(parsed.value) && isV4Graph((parsed.value as any).graph_design)) {
    return { graph: (parsed.value as any).graph_design, asString: false };
  }
  if (isRecord(parsed.value) && isV4Graph((parsed.value as any).graph)) {
    return { graph: (parsed.value as any).graph, asString: false };
  }
  return null;
}

export function graphSignature(graph: VibeGraphDesign): string {
  try {
    return JSON.stringify(graph);
  } catch {
    return String(graph);
  }
}

export function layoutSignature(layout: VibeLayout): string {
  try {
    return JSON.stringify(layout || {});
  } catch {
    return String(layout);
  }
}

export function parseEndpoint(name: string): { base: string; suffix: string | null } {
  const s = String(name || '');
  const idx = s.indexOf('.');
  if (idx === -1) return { base: s, suffix: null };
  return { base: s.slice(0, idx), suffix: s.slice(idx + 1) || null };
}

export function isInternalNodeId(id: string): boolean {
  return (
    id === 'entry' ||
    id === 'exit' ||
    id.endsWith('.entry') ||
    id.endsWith('.exit') ||
    id.endsWith('.controller') ||
    id.endsWith('.terminate')
  );
}

export function allowedKeysForType(type: VibeNodeType): Set<string> {
  // Keep a conservative allowlist for type changes while preserving stage-2 v4 fields
  // (so switching types does not accidentally drop important metadata).
  const common = [
    'name',
    'type',
    'description',
    'label',
    'parent',
    'pull_keys',
    'push_keys',
    'attributes',
    // v4 stage-2 profile fields (preserved/round-tripped by the adapter)
    'scope',
    'agent_id',
    'tools',
    'input_fields',
    'output_fields',
    // internal metadata flags (not saved to JSON; used to avoid injecting optional fields)
    '__gd_has_input_fields',
    '__gd_has_output_fields',
    '__gd_has_pull_keys',
    '__gd_has_push_keys',
    '__gd_has_tools',
    '__gd_has_terminate_prompt',
    '__gd_pull_derived',
    '__gd_push_derived',
    '__gd_raw_v4_type'
  ];
  if (type === 'Loop')
    return new Set([
      ...common,
      'max_iterations',
      'terminate_condition_prompt',
      'terminate_condition_expr',
      'terminate_condition_code'
    ]);
  if (type === 'Agent') return new Set([...common, 'agent', 'instructions', 'prompt_template', 'prompt', 'tools']);
  if (type === 'CustomNode') return new Set([...common, 'forward_body', 'code']);
  if (type === 'LogicSwitch' || type === 'AgentSwitch') return new Set([...common, 'condition_bindings', 'branches']);
  if (type === 'Graph') return new Set(common);
  return new Set(common);
}

export function pickFields(source: Record<string, unknown>, allowed: Set<string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const k of allowed) {
    if (k in source) out[k] = source[k];
  }
  return out;
}

export function parentOfEndpoint(endpoint: string, parentByName: Record<string, string | undefined>): string | undefined {
  const ep = String(endpoint || '');
  if (ep === 'entry' || ep === 'exit') return undefined;
  const { base, suffix } = parseEndpoint(ep);
  if (!suffix) return parentByName[base];
  if (suffix === 'entry' || suffix === 'exit' || suffix === 'controller' || suffix === 'terminate') return base;
  return parentByName[base];
}

export type ExtractedGraphDesign = { graph: VibeGraphDesign; locator: VibeGraphLocator };

export function extractGraphDesign(root: unknown): ExtractedGraphDesign | null {
  const fromV4Graph = (graph: VibeV4Graph, locator: VibeGraphLocator): ExtractedGraphDesign => {
    return { graph: normalizeGraphDesign(fromV4GraphDesign(graph)), locator };
  };

  // Unified spec wrapper: { graph_design: { nodes, edges } }
  if (isRecord(root) && isV4Graph((root as any).graph_design)) {
    return fromV4Graph((root as any).graph_design, { path: ['graph_design'], asString: false });
  }
  if (isRecord(root) && isV4Graph((root as any).graph)) {
    return fromV4Graph((root as any).graph, { path: ['graph'], asString: false });
  }
  if (isV4Graph(root)) {
    return fromV4Graph(root, { path: [], asString: false });
  }
  if (typeof root === 'string') {
    const parsed = tryParseV4GraphString(root);
    if (parsed) return fromV4Graph(parsed.graph, { path: [], asString: parsed.asString });
  }

  // Deep-search for `{ graph: { nodes: [...], edges: [...] } }` within an object/array payload.
  const stack: Array<{ value: unknown; path: Array<string | number>; depth: number }> = [{ value: root, path: [], depth: 0 }];
  const MAX_DEPTH = 10;
  const MAX_ITEMS = 20_000;
  let seen = 0;

  while (stack.length) {
    const cur = stack.pop()!;
    if (seen++ > MAX_ITEMS) break;
    const value = cur.value;
    if (isRecord(value) && isV4Graph((value as any).graph_design)) {
      return fromV4Graph((value as any).graph_design, { path: [...cur.path, 'graph_design'], asString: false });
    }
    if (isRecord(value) && isV4Graph((value as any).graph)) {
      return fromV4Graph((value as any).graph, { path: [...cur.path, 'graph'], asString: false });
    }
    if (typeof value === 'string') {
      const parsed = tryParseV4GraphString(value);
      if (parsed) return fromV4Graph(parsed.graph, { path: cur.path, asString: true });
    }
    if (cur.depth >= MAX_DEPTH) continue;

    if (isRecord(value)) {
      for (const [k, v] of Object.entries(value)) stack.push({ value: v, path: [...cur.path, k], depth: cur.depth + 1 });
      continue;
    }
    if (Array.isArray(value)) {
      const limit = Math.min(value.length, 2000);
      for (let i = 0; i < limit; i++) {
        stack.push({ value: value[i], path: [...cur.path, i], depth: cur.depth + 1 });
      }
      continue;
    }
  }

  return null;
}

export { toV4GraphDesign } from '../utils/vibeGraphDesignV4.js';

export function setAtPath(root: unknown, path: Array<string | number>, next: unknown): boolean {
  if (!path.length) return false;
  let cur: any = root;
  for (let i = 0; i < path.length - 1; i++) {
    const key = path[i] as any;
    if (cur == null) return false;
    cur = cur[key];
  }
  const last = path[path.length - 1] as any;
  if (cur == null) return false;
  cur[last] = next;
  return true;
}
