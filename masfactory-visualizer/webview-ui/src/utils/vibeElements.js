/**
 * Build Cytoscape elements from a Vibe graph_design payload.
 *
 * This is shared between the Vibe editor component and node:test unit tests.
 */

/**
 * @param {unknown} t
 * @returns {string}
 */
function normalizeType(t) {
  const s = typeof t === 'string' ? t : '';
  return s || 'Node';
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
 * @param {string} id
 * @param {string} type
 * @returns {boolean}
 */
function isInternalId(id, type) {
  if (id === 'entry' || id === 'exit') return true;
  if (type === 'entry' || type === 'exit') return true;
  if (type === 'Controller' || type === 'TerminateNode') return true;
  if (id.endsWith('.entry') || id.endsWith('.exit') || id.endsWith('.controller') || id.endsWith('.terminate'))
    return true;
  return false;
}

/**
 * @param {string} id
 * @param {string} type
 * @returns {string}
 */
function labelForNode(id, type) {
  if (type === 'entry' || id === 'entry' || id.endsWith('.entry')) return 'entry';
  if (type === 'exit' || id === 'exit' || id.endsWith('.exit')) return 'exit';
  if (type === 'Controller' || id.endsWith('.controller')) return 'controller';
  if (type === 'TerminateNode' || id.endsWith('.terminate')) return 'terminate';
  if (type && type !== 'Node') return `${id} (${type})`;
  return id;
}

/**
 * Estimate node size without relying on renderer text measurement.
 * This avoids rare cases where label-based sizing can resolve to 0 and make nodes invisible.
 *
 * @param {string} label
 * @param {string} type
 * @returns {{ w: number; h: number }}
 */
function estimateNodeSize(label, type) {
  const t = String(type || '');
  if (t === 'entry' || t === 'exit' || t === 'Controller' || t === 'TerminateNode') {
    return { w: 70, h: 35 };
  }
  if (t === 'Graph' || t === 'Loop') {
    return { w: 240, h: 180 };
  }

  const text = String(label || '');
  const lines = text.split('\n');
  const maxLine = Math.max(1, ...lines.map((l) => l.length));
  const charWidth = 7.2;
  const lineHeight = 14;
  const paddingX = 34;
  const paddingY = 26;
  const w = Math.max(90, Math.min(520, Math.round(maxLine * charWidth + paddingX)));
  const h = Math.max(40, Math.min(260, Math.round(lines.length * lineHeight + paddingY)));
  return { w, h };
}

/**
 * @param {unknown} value
 * @returns {value is { x: number; y: number }}
 */
function isValidPos(value) {
  if (!value || typeof value !== 'object') return false;
  const any = /** @type {any} */ (value);
  return (
    typeof any.x === 'number' &&
    Number.isFinite(any.x) &&
    typeof any.y === 'number' &&
    Number.isFinite(any.y)
  );
}

/**
 * @param {{ Nodes?: any[]; Edges?: any[] }} graph
 * @param {Record<string, { x: number; y: number }>} positions
 * @param {Set<string>} invalidNodes
 * @param {Set<number>} invalidEdges
 * @returns {import('cytoscape').ElementDefinition[]}
 */
export function buildVibeElements(graph, positions, invalidNodes, invalidEdges) {
  /** @type {import('cytoscape').ElementDefinition[]} */
  const elements = [];

  /** @type {Record<string, string>} */
  const nodeTypes = {};
  /** @type {Record<string, string | undefined>} */
  const nodeParents = {};
  /** @type {Set<string>} */
  const nodeNames = new Set();

  // Root boundary nodes
  nodeNames.add('entry');
  nodeNames.add('exit');
  nodeTypes.entry = 'entry';
  nodeTypes.exit = 'exit';

  const nodes = Array.isArray(graph?.Nodes) ? graph.Nodes : [];
  for (const n of nodes) {
    if (!n || typeof n !== 'object') continue;
    const name = String(n.name || '');
    if (!name) continue;
    nodeNames.add(name);
    nodeTypes[name] = normalizeType(n.type);
    const parent = typeof n.parent === 'string' && n.parent.trim() ? String(n.parent) : undefined;
    if (parent) nodeParents[name] = parent;
  }

  // Some graph_design formats omit explicit `parent`.
  // Best-effort infer Loop membership from `.controller` reachability so loop bodies render as a subgraph.
  const edgesForInference = Array.isArray(graph?.Edges) ? graph.Edges : [];
  /** @type {Map<string, string[]>} */
  const adj = new Map();
  /** @type {Map<string, string[]>} */
  const rev = new Map();
  const addAdj = (from, to) => {
    const a = adj.get(from) || [];
    a.push(to);
    adj.set(from, a);
    const r = rev.get(to) || [];
    r.push(from);
    rev.set(to, r);
  };
  for (const e of edgesForInference) {
    const from = String(e?.from || '');
    const to = String(e?.to || '');
    if (!from || !to) continue;
    addAdj(from, to);
  }
  const walk = (start, map) => {
    const seen = new Set();
    /** @type {string[]} */
    const stack = [start];
    while (stack.length && seen.size < 5000) {
      const cur = stack.pop();
      if (!cur) break;
      if (seen.has(cur)) continue;
      seen.add(cur);
      const out = map.get(cur) || [];
      for (const v of out) {
        if (!seen.has(v)) stack.push(v);
      }
    }
    return seen;
  };

  // Add internal boundary endpoints for Graph/Loop nodes.
  for (const name of Array.from(nodeNames)) {
    const t = nodeTypes[name];
    if (t === 'Graph') {
      const entryId = `${name}.entry`;
      const exitId = `${name}.exit`;
      nodeNames.add(entryId);
      nodeNames.add(exitId);
      nodeTypes[entryId] = 'entry';
      nodeTypes[exitId] = 'exit';
      nodeParents[entryId] = name;
      nodeParents[exitId] = name;
    } else if (t === 'Loop') {
      const controllerId = `${name}.controller`;
      nodeNames.add(controllerId);
      nodeTypes[controllerId] = 'Controller';
      nodeParents[controllerId] = name;

      // Optional early-break endpoint for v4 loop sub-graphs.
      const terminateId = `${name}.terminate`;
      const hasTerminate =
        Array.isArray(graph?.Edges) &&
        graph.Edges.some((e) => String(e?.from || '') === terminateId || String(e?.to || '') === terminateId);
      if (hasTerminate) {
        nodeNames.add(terminateId);
        nodeTypes[terminateId] = 'TerminateNode';
        nodeParents[terminateId] = name;
      }
    }
  }

  // Infer loop body nodes (reachable from controller and can reach controller).
  for (const name of Array.from(nodeNames)) {
    const t = nodeTypes[name];
    if (t !== 'Loop') continue;
    const controllerId = `${name}.controller`;
    if (!adj.has(controllerId) && !rev.has(controllerId)) continue;
    const forward = walk(controllerId, adj);
    const backward = walk(controllerId, rev);
    for (const ep of forward) {
      if (!backward.has(ep)) continue;
      const { base, suffix } = parseEndpoint(ep);
      if (suffix) continue;
      if (!base || base === 'entry' || base === 'exit' || base === name) continue;
      if (!nodeNames.has(base)) continue;
      if (nodeTypes[base] === 'Loop') continue;
      if (nodeParents[base]) continue;
      nodeParents[base] = name;
    }
  }

  // Ensure compound parents exist for any referenced parent.
  for (const parent of Object.values(nodeParents)) {
    if (!parent) continue;
    nodeNames.add(parent);
    if (!nodeTypes[parent]) nodeTypes[parent] = 'Graph';
  }

  /** @type {Set<string>} */
  const subgraphParents = new Set();
  for (const id of nodeNames) {
    const t = nodeTypes[id] || 'Node';
    if (t === 'Graph' || t === 'Loop') {
      subgraphParents.add(id);
    }
  }

  /** @type {Record<string, { x: number; y: number }>} */
  const fallbackPos = {};
  const orderedIds = Array.from(nodeNames);
  const count = orderedIds.length;
  const cols = Math.max(1, Math.ceil(Math.sqrt(count)));
  for (let i = 0; i < count; i++) {
    const id = orderedIds[i];
    fallbackPos[id] = { x: (i % cols) * 240, y: Math.floor(i / cols) * 160 };
  }

  const invalidNodeSet = invalidNodes instanceof Set ? invalidNodes : new Set();
  const invalidEdgeSet = invalidEdges instanceof Set ? invalidEdges : new Set();

  for (const id of nodeNames) {
    const type = nodeTypes[id] || 'Node';
    const parent = nodeParents[id];
    const isParent = subgraphParents.has(id);
    const invalid = invalidNodeSet.has(id);
    const label = labelForNode(id, type);
    const size = estimateNodeSize(label, type);
    const candidate = positions ? positions[id] : undefined;
    const pos = isValidPos(candidate) ? candidate : fallbackPos[id];
    elements.push({
      group: 'nodes',
      data: {
        id,
        label,
        type,
        parent: parent || undefined,
        internal: isInternalId(id, type) ? '1' : '0',
        w: size.w,
        h: size.h
      },
      // Avoid setting compound parent positions from persisted layouts. Updating a parent position
      // translates all descendants and can scramble a stable layout after reload/tab switches.
      position: !isParent && pos ? { x: pos.x, y: pos.y } : undefined,
      classes: `${isParent ? 'subgraph ' : ''}${invalid ? 'invalid' : ''}`.trim()
    });
  }

  const edges = Array.isArray(graph?.Edges) ? graph.Edges : [];
  for (let i = 0; i < edges.length; i++) {
    const e = edges[i];
    const from = String(e?.from || '');
    const to = String(e?.to || '');
    if (!from || !to) continue;
    if (!nodeNames.has(from) || !nodeNames.has(to)) continue;

    const cond = typeof e?.condition === 'string' ? String(e.condition).trim() : '';
    const label = cond;

    elements.push({
      group: 'edges',
      data: {
        id: `edge:${i}`,
        source: from,
        target: to,
        label,
        edgeIndex: String(i)
      },
      classes: invalidEdgeSet.has(i) ? 'invalid-edge' : ''
    });
  }

  return elements;
}
