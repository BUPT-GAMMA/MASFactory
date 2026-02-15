/**
 * V4 `graph_design.json` adapter utilities.
 *
 * Kept as a JS module (with d.ts) so node:test can import it without a TS runtime.
 *
 * Unified graph_design schema:
 * `{ "nodes": [...], "edges": [...] }` (cache inner shape), optionally wrapped by:
 * `{ "graph_design": { "nodes": [...], "edges": [...] } }` (LLM output shape).
 *
 * Nodes are:
 * - Action (agent required)
 * - Switch
 * - Loop (with sub_graph using CONTROLLER/TERMINATE)
 * - Subgraph (with sub_graph using ENTRY/EXIT)
 *
 * Compatibility:
 * - Older payloads may still use `id` for node name.
 * - START/END endpoints are accepted on load and normalized to ENTRY/EXIT on save.
 * - `{ "graph": { ... } }` is still accepted on load, but save output stays in unified shape.
 */

/**
 * @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function isRecord(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

/**
 * @param {unknown} value
 * @returns {value is import('./vibeGraphDesignV4.d.ts').VibeV4Graph}
 */
export function isV4Graph(value) {
  if (!isRecord(value)) return false;
  if (!Array.isArray(value.nodes) || !Array.isArray(value.edges)) return false;
  return true;
}

/**
 * @param {unknown} raw
 * @returns {string}
 */
function normalizeV4NodeType(raw) {
  const t = typeof raw === 'string' ? raw.trim() : '';
  switch (t) {
    case 'Action':
      return 'Agent';
    case 'Switch':
      return 'LogicSwitch';
    case 'Loop':
      return 'Loop';
    case 'Subgraph':
      return 'Graph';
    default:
      return 'Agent';
  }
}

/**
 * @param {unknown} type
 * @returns {'Action' | 'Switch' | 'Loop' | 'Subgraph'}
 */
function internalTypeToV4(type) {
  const t = typeof type === 'string' ? type : '';
  if (t === 'Loop') return 'Loop';
  if (t === 'Graph') return 'Subgraph';
  if (t === 'LogicSwitch' || t === 'AgentSwitch') return 'Switch';
  return 'Action';
}

/**
 * @param {string} name
 * @returns {{ base: string; suffix: string | null }}
 */
function parseEndpoint(name) {
  const s = String(name || '');
  const idx = s.indexOf('.');
  if (idx === -1) return { base: s, suffix: null };
  return { base: s.slice(0, idx), suffix: s.slice(idx + 1) || null };
}

/**
 * @param {string} endpoint
 * @param {Record<string, string | undefined>} parentByName
 * @returns {string | undefined}
 */
function parentOfEndpoint(endpoint, parentByName) {
  const ep = String(endpoint || '');
  if (ep === 'entry' || ep === 'exit') return undefined;
  const { base, suffix } = parseEndpoint(ep);
  if (!suffix) return parentByName[base];
  if (suffix === 'entry' || suffix === 'exit' || suffix === 'controller' || suffix === 'terminate') return base;
  return parentByName[base];
}

/**
 * @param {{ endpoint: string; scopeKind: 'root' | 'subgraph' | 'loop'; scopeNodeName: string | null; idMap: Map<string, string> }} args
 * @returns {string}
 */
function v4EndpointToInternal(args) {
  const ep = String(args.endpoint || '').trim();
  if (!ep) return '';
  const upper = ep.toUpperCase();

  if (args.scopeKind === 'loop') {
    if (upper === 'CONTROLLER') return args.scopeNodeName ? `${args.scopeNodeName}.controller` : 'controller';
    if (upper === 'TERMINATE') return args.scopeNodeName ? `${args.scopeNodeName}.terminate` : 'terminate';
    return args.idMap.get(ep) || args.idMap.get(upper) || ep;
  }

  // root/subgraph
  if (upper === 'START' || upper === 'ENTRY') return args.scopeNodeName ? `${args.scopeNodeName}.entry` : 'entry';
  if (upper === 'END' || upper === 'EXIT') return args.scopeNodeName ? `${args.scopeNodeName}.exit` : 'exit';
  return args.idMap.get(ep) || args.idMap.get(upper) || ep;
}

/**
 * @param {{ endpoint: string; scopeKind: 'root' | 'subgraph' | 'loop'; scopeName: string | null }} args
 * @returns {string}
 */
function internalEndpointToV4(args) {
  const ep = String(args.endpoint || '').trim();
  if (!ep) return '';

  if (args.scopeKind === 'loop') {
    if (args.scopeName && ep === `${args.scopeName}.controller`) return 'CONTROLLER';
    if (args.scopeName && ep === `${args.scopeName}.terminate`) return 'TERMINATE';
    return ep;
  }

  if (args.scopeName) {
    if (ep === `${args.scopeName}.entry`) return 'ENTRY';
    if (ep === `${args.scopeName}.exit`) return 'EXIT';
    return ep;
  }

  if (ep === 'entry') return 'ENTRY';
  if (ep === 'exit') return 'EXIT';
  return ep;
}

/**
 * Convert internal key dictionaries (pull_keys/push_keys) into a v4 input/output list.
 *
 * @param {unknown} keys
 * @returns {string[]}
 */
function keysFieldToList(keys) {
  if (keys === undefined) return [];
  if (keys === null) return [];
  if (Array.isArray(keys)) return keys.map((k) => String(k)).filter((k) => k.trim());
  if (typeof keys === 'object') {
    return Object.keys(keys).map((k) => String(k)).filter((k) => k.trim());
  }
  return [];
}

/**
 * Flatten a v4 graph (recursive) into the editor's internal `{ Nodes, Edges }` representation.
 *
 * @param {{ graph: import('./vibeGraphDesignV4.d.ts').VibeV4Graph; scopeKind: 'root' | 'subgraph' | 'loop'; scopeNodeName: string | null; usedNames: Set<string> }} args
 * @returns {{ nodes: any[]; edges: any[] }}
 */
function flattenV4(args) {
  /** @type {any[]} */
  const nodesOut = [];
  /** @type {any[]} */
  const edgesOut = [];

  /** @type {Map<string, string>} */
  const idMap = new Map();
  const reservedNodeKeys = new Set(['name', 'id', 'type', 'label', 'agent', 'sub_graph']);
  const reservedEdgeKeys = new Set(['source', 'target', 'condition', 'key', 'keys']);

  const makeUnique = (base) => {
    const trimmed = String(base || '').trim();
    if (!trimmed) return '';
    if (!args.usedNames.has(trimmed)) return trimmed;
    let i = 2;
    while (args.usedNames.has(`${trimmed}_${i}`)) i += 1;
    return `${trimmed}_${i}`;
  };

  const nodes = Array.isArray(args.graph.nodes) ? args.graph.nodes : [];
  for (const raw of nodes) {
    if (!isRecord(raw)) continue;
    const localId = String(raw.name || raw.id || '').trim();
    if (!localId) continue;
    const name = makeUnique(localId);
    idMap.set(localId, name);
    args.usedNames.add(name);

    const rawV4Type = typeof raw.type === 'string' ? raw.type.trim() : '';
    const type = normalizeV4NodeType(rawV4Type);
    const label = typeof raw.label === 'string' ? raw.label.trim() : '';
    const agent = typeof raw.agent === 'string' ? raw.agent.trim() : '';

    /** @type {any} */
    const spec = {
      name,
      type,
      label: label || undefined,
      parent: args.scopeNodeName || undefined
    };
    if (rawV4Type) spec.__gd_raw_v4_type = rawV4Type;
    if (type === 'Agent') spec.agent = agent || undefined;

    // Preserve any extra fields (scope, agent_id, tools, input_fields, output_fields, instructions, ...)
    // while keeping the internal editor shape (name/type/parent).
    for (const [k, v] of Object.entries(raw)) {
      if (reservedNodeKeys.has(k)) continue;
      // avoid accidentally overriding editor-specific fields
      if (k === 'name' || k === 'parent') continue;
      spec[k] = v;
    }

    nodesOut.push(spec);

    if ((type === 'Graph' || type === 'Loop') && isV4Graph(raw.sub_graph)) {
      const nested = flattenV4({
        graph: raw.sub_graph,
        scopeKind: type === 'Loop' ? 'loop' : 'subgraph',
        scopeNodeName: name,
        usedNames: args.usedNames
      });
      nodesOut.push(...nested.nodes);
      edgesOut.push(...nested.edges);
    }
  }

  const edges = Array.isArray(args.graph.edges) ? args.graph.edges : [];
  for (const raw of edges) {
    if (!isRecord(raw)) continue;
    const source = String(raw.source || '').trim();
    const target = String(raw.target || '').trim();
    if (!source || !target) continue;
    const from = v4EndpointToInternal({ endpoint: source, scopeKind: args.scopeKind, scopeNodeName: args.scopeNodeName, idMap });
    const to = v4EndpointToInternal({ endpoint: target, scopeKind: args.scopeKind, scopeNodeName: args.scopeNodeName, idMap });
    if (!from || !to) continue;
    /** @type {any} */
    const e = { from, to };
    if (Object.prototype.hasOwnProperty.call(raw, 'condition')) {
      e.condition = raw.condition;
    }
    if (Object.prototype.hasOwnProperty.call(raw, 'keys')) {
      e.keys = raw.keys;
    } else if (Object.prototype.hasOwnProperty.call(raw, 'key')) {
      // Legacy alias for unified edge keys.
      e.keys = raw.key;
    }
    for (const [k, v] of Object.entries(raw)) {
      if (reservedEdgeKeys.has(k)) continue;
      e[k] = v;
    }
    edgesOut.push(e);
  }

  return { nodes: nodesOut, edges: edgesOut };
}

/**
 * @param {import('./vibeGraphDesignV4.d.ts').VibeV4Graph} graph
 * @returns {import('../stores/vibe').VibeGraphDesign}
 */
export function fromV4GraphDesign(graph) {
  const usedNames = new Set();
  const flat = flattenV4({ graph, scopeKind: 'root', scopeNodeName: null, usedNames });
  return { Nodes: flat.nodes, Edges: flat.edges };
}

/**
  * Convert the internal `{ Nodes, Edges }` graph into v4 `{ nodes, edges }`, recursively.
  *
  * Unified graph_design output requirements:
   * - node id field is `name` (legacy `id` is load-only compatibility)
  * - edge fields are normalized to `source`, `target`, and optional `condition` / `keys`
  *
  * @param {import('../stores/vibe').VibeGraphDesign} graph
  * @returns {import('./vibeGraphDesignV4.d.ts').VibeV4Graph}
  */
export function toV4GraphDesign(graph) {
  const nodes = Array.isArray(graph?.Nodes) ? graph.Nodes : [];
  const edges = Array.isArray(graph?.Edges) ? graph.Edges : [];

  /** @type {Record<string, string | undefined>} */
  const parentByName = {};
  /** @type {Record<string, any>} */
  const nodeByName = {};
  for (const n of nodes) {
    if (!n || typeof n !== 'object') continue;
    const name = String(n.name || '').trim();
    if (!name) continue;
    const parent = typeof n.parent === 'string' && n.parent.trim() ? n.parent.trim() : undefined;
    parentByName[name] = parent;
    nodeByName[name] = n;
  }

  const omitNodeKeys = new Set([
    // internal editor/model fields
    'name',
    'type',
    'parent',
    // handled explicitly below (to control emission of optional fields)
    'tools',
    'terminate_condition_prompt',
    'pull_keys',
    'push_keys',
    'attributes',
    'condition_bindings',
    'branches',
    'forward_body',
    'code',
    'terminate_condition_expr',
    'terminate_condition_code',
    // legacy / deprecated fields (do not emit in the unified graph_design format)
    'terminate_condition',
    'tools_allowed',
    // internal metadata flags (not part of graph_design spec)
    '__gd_has_input_fields',
    '__gd_has_output_fields',
    '__gd_has_pull_keys',
    '__gd_has_push_keys',
    '__gd_has_tools',
    '__gd_has_terminate_prompt',
    '__gd_pull_derived',
    '__gd_push_derived',
    '__gd_raw_v4_type',
  ]);
  /** @param {string} nodeName @returns {string} */
  const scopeForNode = (nodeName) => {
    const chain = [];
    let cur = parentByName[nodeName];
    let guard = 0;
    while (cur && guard++ < 50) {
      chain.push(cur);
      cur = parentByName[cur];
    }
    chain.reverse();
    return chain.length ? `root/${chain.join('/')}` : 'root';
  };

  /** @param {string | null} scopeName @param {'root' | 'subgraph' | 'loop'} scopeKind */
  const buildScope = (scopeName, scopeKind) => {
    const scopeNodes = nodes.filter((n) => {
      const name = String(n?.name || '').trim();
      if (!name) return false;
      const parent = parentByName[name];
      return scopeName ? parent === scopeName : !parent;
    });

    /** @type {import('./vibeGraphDesignV4.d.ts').VibeV4Node[]} */
    const outNodes = [];
    for (const n of scopeNodes) {
      const name = String(n?.name || '').trim();
      if (!name) continue;
      const type = internalTypeToV4(n?.type);
      const label =
        (typeof n?.label === 'string' && n.label.trim()) ||
        (typeof n?.description === 'string' && n.description.trim()) ||
        name;
      const agent = typeof n?.agent === 'string' ? n.agent.trim() : '';

      /** @type {import('./vibeGraphDesignV4.d.ts').VibeV4Node} */
      const out = { name, type, label };
      if (type === 'Action' && agent) out.agent = agent;

      // Preserve v4 stage-2 node fields (scope, agent_id, tools_allowed, input_fields, output_fields, instructions, ...)
      // while omitting internal editor-only fields.
      for (const [k, v] of Object.entries(n || {})) {
        if (omitNodeKeys.has(k)) continue;
        if (k === 'label' || k === 'agent') continue;
        if (k === 'sub_graph') continue;
        if (v === undefined) continue;
        out[k] = v;
      }

      // Keep `scope` consistent with graph nesting if the field is present.
      if (Object.prototype.hasOwnProperty.call(n || {}, 'scope')) {
        out.scope = scopeForNode(name);
      }

      // Action execution field: tools (allowed tool names)
      const hasTools =
        !!n && Object.prototype.hasOwnProperty.call(n, '__gd_has_tools')
          ? !!n.__gd_has_tools
          : Object.prototype.hasOwnProperty.call(n || {}, 'tools');
      const tools = (n || {}).tools;
      if (Array.isArray(tools)) {
        if (hasTools || tools.length > 0) out.tools = tools;
      } else if (typeof tools === 'string') {
        const trimmed = tools.trim();
        if (trimmed) out.tools = trimmed.split(/[\n,]+/g).map((s) => s.trim()).filter(Boolean);
      }

      // Loop execution field: terminate_condition_prompt (omit if blank unless it existed before).
      const hasTerminatePrompt =
        !!n && Object.prototype.hasOwnProperty.call(n, '__gd_has_terminate_prompt')
          ? !!n.__gd_has_terminate_prompt
          : Object.prototype.hasOwnProperty.call(n || {}, 'terminate_condition_prompt');
      const terminatePrompt = typeof (n || {}).terminate_condition_prompt === 'string' ? String((n || {}).terminate_condition_prompt) : '';
      if (terminatePrompt.trim()) {
        out.terminate_condition_prompt = terminatePrompt;
      } else if (hasTerminatePrompt) {
        // Preserve explicit empty value if the source included the field.
        out.terminate_condition_prompt = terminatePrompt;
      }

      // Unified graph_design dataflow fields:
      // - input_fields/output_fields are list[str]
      // - pull_keys/push_keys are dict[str,str]
      // Emit fields only if they existed in the original payload OR the user filled non-empty values.
      const hasInputFields = !!n && Object.prototype.hasOwnProperty.call(n, '__gd_has_input_fields')
        ? !!(n).__gd_has_input_fields
        : Object.prototype.hasOwnProperty.call(n || {}, 'input_fields');
      const hasOutputFields = !!n && Object.prototype.hasOwnProperty.call(n, '__gd_has_output_fields')
        ? !!(n).__gd_has_output_fields
        : Object.prototype.hasOwnProperty.call(n || {}, 'output_fields');
      const hasPullKeys = !!n && Object.prototype.hasOwnProperty.call(n, '__gd_has_pull_keys')
        ? !!(n).__gd_has_pull_keys
        : Object.prototype.hasOwnProperty.call(n || {}, 'pull_keys');
      const hasPushKeys = !!n && Object.prototype.hasOwnProperty.call(n, '__gd_has_push_keys')
        ? !!(n).__gd_has_push_keys
        : Object.prototype.hasOwnProperty.call(n || {}, 'push_keys');

      const pullList = keysFieldToList(n?.pull_keys);
      const pushList = keysFieldToList(n?.push_keys);

      const pullDict = n?.pull_keys && typeof n.pull_keys === 'object' && !Array.isArray(n.pull_keys) ? n.pull_keys : null;
      const pushDict = n?.push_keys && typeof n.push_keys === 'object' && !Array.isArray(n.push_keys) ? n.push_keys : null;

      const hasNonEmptyDict = (d) => {
        if (!d || typeof d !== 'object') return false;
        const keys = Object.keys(d);
        if (keys.length === 0) return false;
        for (const k of keys) {
          const v = d[k];
          if (v != null && String(v).trim()) return true;
        }
        return false;
      };

      if (hasInputFields || pullList.length > 0) {
        // Keep input_fields in sync with pull_keys keys.
        out.input_fields = pullList;
      }
      if (hasOutputFields || pushList.length > 0) {
        out.output_fields = pushList;
      }
      // Only emit pull_keys/push_keys if they existed before, or if the user provided descriptions.
      if (hasPullKeys || hasNonEmptyDict(pullDict)) {
        out.pull_keys = pullDict || {};
      }
      if (hasPushKeys || hasNonEmptyDict(pushDict)) {
        out.push_keys = pushDict || {};
      }

      if (type === 'Loop' || type === 'Subgraph') {
        out.sub_graph = buildScope(name, type === 'Loop' ? 'loop' : 'subgraph');
      }
      outNodes.push(out);
    }

    /** @type {import('./vibeGraphDesignV4.d.ts').VibeV4Edge[]} */
    const outEdges = [];
    const omitEdgeKeys = new Set(['from', 'to', 'condition', 'keys', '__gd_has_keys']);
    for (const e of edges) {
      const from = String(e?.from || '').trim();
      const to = String(e?.to || '').trim();
      if (!from || !to) continue;
      const pf = parentOfEndpoint(from, parentByName);
      const pt = parentOfEndpoint(to, parentByName);
      if ((pf || null) !== scopeName || (pt || null) !== scopeName) continue;

      const source = internalEndpointToV4({ endpoint: from, scopeKind, scopeName });
      const target = internalEndpointToV4({ endpoint: to, scopeKind, scopeName });
      if (!source || !target) continue;

      /** @type {import('./vibeGraphDesignV4.d.ts').VibeV4Edge} */
      const out = { source, target };
      if (Object.prototype.hasOwnProperty.call(e || {}, 'condition')) {
        const cond = (e || {}).condition;
        out.condition = cond == null ? '' : String(cond);
      }
      const hasKeys =
        !!e && Object.prototype.hasOwnProperty.call(e, '__gd_has_keys') ? !!e.__gd_has_keys : false;
      const keysVal = (e || {}).keys;
      const hasNonEmptyKeys = (() => {
        if (!keysVal || typeof keysVal !== 'object') return false;
        if (Array.isArray(keysVal)) return keysVal.length > 0;
        return Object.keys(keysVal).length > 0;
      })();
      if (hasKeys || hasNonEmptyKeys) {
        out.keys = keysVal == null ? {} : keysVal;
      }

      outEdges.push(out);
    }

    return { nodes: outNodes, edges: outEdges };
  };

  return buildScope(null, 'root');
}
