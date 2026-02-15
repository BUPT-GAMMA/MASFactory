/**
 * Vibe graph_design validation helpers.
 *
 * Kept as a JS module (with d.ts) so node:test can import it without a TS runtime.
 */

const NAME_PATTERN = /^[A-Za-z0-9_-]+$/;
const RESERVED_NODE_NAMES = new Set(['ENTRY', 'EXIT', 'CONTROLLER', 'TERMINATE']);

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
 * @typedef {{ message: string; nodes: string[]; edges: number[] }} GraphIssue
 */

/**
 * @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function isRecord(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

/**
 * @param {string} from
 * @param {string} to
 * @param {{ Nodes?: any[] }} g
 * @returns {boolean}
 */
export function isSameLevelEdge(from, to, g) {
  const nodes = Array.isArray(g?.Nodes) ? g.Nodes : [];
  /** @type {Record<string, string | undefined>} */
  const parentByName = {};
  for (const n of nodes) {
    if (!isRecord(n)) continue;
    const name = String(n.name || '').trim();
    if (!name) continue;
    const parent = typeof n.parent === 'string' && n.parent.trim() ? String(n.parent) : undefined;
    parentByName[name] = parent;
  }
  return parentOfEndpoint(from, parentByName) === parentOfEndpoint(to, parentByName);
}

/**
 * @param {string} endpoint
 * @param {Set<string>} nodeNames
 * @param {Record<string, string>} typeByName
 * @returns {boolean}
 */
function endpointExists(endpoint, nodeNames, typeByName) {
  const ep = String(endpoint || '').trim();
  if (!ep) return false;
  if (ep === 'entry' || ep === 'exit') return true;
  const { base, suffix } = parseEndpoint(ep);
  if (!nodeNames.has(base)) return false;
  if (!suffix) return true;
  if (suffix === 'entry' || suffix === 'exit') return typeByName[base] === 'Graph' || typeByName[base] === 'Subgraph';
  if (suffix === 'controller' || suffix === 'terminate') return typeByName[base] === 'Loop';
  return false;
}

/**
 * @param {string | undefined} scopeName
 * @param {Record<string, string>} typeByName
 * @returns {'root' | 'subgraph' | 'loop'}
 */
function scopeKind(scopeName, typeByName) {
  if (!scopeName) return 'root';
  return typeByName[scopeName] === 'Loop' ? 'loop' : 'subgraph';
}

/**
 * @param {string} endpoint
 * @param {Set<string>} nodeNames
 * @returns {string | null}
 */
function endpointToNode(endpoint, nodeNames) {
  const { base, suffix } = parseEndpoint(endpoint);
  if (suffix) return null;
  if (!nodeNames.has(base)) return null;
  return base;
}

/**
 * @param {Map<string, string[]>} adj
 * @param {string} start
 * @returns {Set<string>}
 */
function reachable(adj, start) {
  /** @type {Set<string>} */
  const seen = new Set();
  /** @type {string[]} */
  const stack = [start];
  while (stack.length) {
    const cur = stack.pop();
    if (!cur || seen.has(cur)) continue;
    seen.add(cur);
    const out = adj.get(cur) || [];
    for (const to of out) {
      if (!seen.has(to)) stack.push(to);
    }
  }
  return seen;
}

/**
 * Validate a graph_design structure.
 *
 * @param {{ Nodes?: any[]; Edges?: any[] }} g
 * @returns {{ issues: GraphIssue[]; invalidNodes: Set<string>; invalidEdges: Set<number> }}
 */
export function validateGraphDesign(g) {
  /** @type {GraphIssue[]} */
  const issues = [];
  /** @type {Set<string>} */
  const invalidNodes = new Set();
  /** @type {Set<number>} */
  const invalidEdges = new Set();

  const nodes = Array.isArray(g?.Nodes) ? g.Nodes : [];
  const edges = Array.isArray(g?.Edges) ? g.Edges : [];

  /** @type {Set<string>} */
  const nodeNames = new Set();
  /** @type {Record<string, any>} */
  const nodeByName = {};
  /** @type {Record<string, string>} */
  const typeByName = {};
  /** @type {Record<string, string | undefined>} */
  const parentByName = {};

  // -------- Node-level checks --------
  for (const n of nodes) {
    if (!isRecord(n)) continue;
    const name = String(n.name || '').trim();
    if (!name) continue;

    if (nodeNames.has(name)) {
      issues.push({ message: `Duplicate node name: ${name}`, nodes: [name], edges: [] });
      invalidNodes.add(name);
    }

    nodeNames.add(name);
    nodeByName[name] = n;
    typeByName[name] = String(n.type || 'Agent');
    const parent = typeof n.parent === 'string' && n.parent.trim() ? n.parent.trim() : undefined;
    parentByName[name] = parent;

    if (!NAME_PATTERN.test(name)) {
      invalidNodes.add(name);
      issues.push({
        message: `Node name "${name}" must match [A-Za-z0-9_-]+`,
        nodes: [name],
        edges: []
      });
    }

    if (RESERVED_NODE_NAMES.has(name.toUpperCase())) {
      invalidNodes.add(name);
      issues.push({
        message: `Node name "${name}" conflicts with built-in endpoint names`,
        nodes: [name],
        edges: []
      });
    }

    if (typeByName[name] === 'Agent' || typeByName[name] === 'Action') {
      const agent = typeof n.agent === 'string' ? n.agent.trim() : '';
      if (!agent) {
        invalidNodes.add(name);
        issues.push({
          message: `Action node "${name}" requires non-empty "agent"`,
          nodes: [name],
          edges: []
        });
      }
    }
  }

  // Parent validity.
  for (const name of nodeNames) {
    const parent = parentByName[name];
    if (!parent) continue;
    if (!nodeNames.has(parent)) {
      invalidNodes.add(name);
      issues.push({ message: `Node ${name} has unknown parent: ${parent}`, nodes: [name], edges: [] });
      continue;
    }
    const pt = typeByName[parent];
    if (pt !== 'Graph' && pt !== 'Subgraph' && pt !== 'Loop') {
      invalidNodes.add(name);
      invalidNodes.add(parent);
      issues.push({
        message: `Node ${name} parent must be Graph/Subgraph/Loop (got ${pt})`,
        nodes: [name, parent],
        edges: []
      });
    }

    // Parent cycle.
    const seen = new Set();
    let cur = parent;
    while (cur) {
      if (cur === name) {
        invalidNodes.add(name);
        invalidNodes.add(parent);
        issues.push({ message: `Parent cycle detected at node ${name}`, nodes: [name, parent], edges: [] });
        break;
      }
      if (seen.has(cur)) break;
      seen.add(cur);
      cur = parentByName[cur];
    }
  }

  /**
   * Record used by scope-level validations.
   * @typedef {{
   *   idx: number;
   *   from: string;
   *   to: string;
   *   scopeName: string | undefined;
   *   scopeKind: 'root' | 'subgraph' | 'loop';
   * }} EdgeRecord
   */

  /** @type {EdgeRecord[]} */
  const validEdgeRecords = [];
  /** @type {Map<string, number[]>} */
  const validOutgoingByNode = new Map();

  const pushOutgoing = (nodeName, edgeIdx) => {
    const list = validOutgoingByNode.get(nodeName) || [];
    list.push(edgeIdx);
    validOutgoingByNode.set(nodeName, list);
  };

  // -------- Edge-level checks --------
  for (let i = 0; i < edges.length; i++) {
    const e = edges[i];
    const from = String(e?.from || '').trim();
    const to = String(e?.to || '').trim();
    if (!from || !to) {
      invalidEdges.add(i);
      issues.push({ message: `Edge[${i}] is missing from/to`, nodes: [], edges: [i] });
      continue;
    }

    if (from === to) {
      invalidEdges.add(i);
      issues.push({ message: `Edge[${i}] is a self-loop (${from})`, nodes: [from], edges: [i] });
    }

    const fromExists = endpointExists(from, nodeNames, typeByName);
    const toExists = endpointExists(to, nodeNames, typeByName);
    if (!fromExists || !toExists) {
      invalidEdges.add(i);
      issues.push({
        message: `Edge[${i}] refers to unknown endpoint(s): ${from} -> ${to}`,
        nodes: [],
        edges: [i]
      });
      continue;
    }

    const fromParent = parentOfEndpoint(from, parentByName);
    const toParent = parentOfEndpoint(to, parentByName);
    if (fromParent !== toParent) {
      invalidEdges.add(i);
      issues.push({
        message: `Cross-level edge[${i}] (${from} -> ${to})`,
        nodes: [],
        edges: [i]
      });
      continue;
    }

    const kind = scopeKind(fromParent, typeByName);
    const fromParsed = parseEndpoint(from);
    const toParsed = parseEndpoint(to);

    const isEntryTarget = to === 'entry' || toParsed.suffix === 'entry';
    const isExitSource = from === 'exit' || fromParsed.suffix === 'exit';
    if (isEntryTarget) {
      invalidEdges.add(i);
      issues.push({ message: `Edge[${i}] cannot target ENTRY endpoint: ${to}`, nodes: [], edges: [i] });
    }
    if (isExitSource) {
      invalidEdges.add(i);
      issues.push({ message: `Edge[${i}] cannot originate from EXIT endpoint: ${from}`, nodes: [], edges: [i] });
    }

    if (fromParsed.suffix === 'terminate') {
      invalidEdges.add(i);
      issues.push({
        message: `Edge[${i}] cannot originate from TERMINATE endpoint: ${from}`,
        nodes: [],
        edges: [i]
      });
    }

    if (kind === 'loop') {
      const usesEntryExit =
        from === 'entry' ||
        to === 'exit' ||
        fromParsed.suffix === 'entry' ||
        fromParsed.suffix === 'exit' ||
        toParsed.suffix === 'entry' ||
        toParsed.suffix === 'exit';
      if (usesEntryExit) {
        invalidEdges.add(i);
        issues.push({
          message: `Loop edge[${i}] cannot use ENTRY/EXIT endpoints: ${from} -> ${to}`,
          nodes: [],
          edges: [i]
        });
      }
    } else {
      const usesLoopBuiltins =
        fromParsed.suffix === 'controller' ||
        fromParsed.suffix === 'terminate' ||
        toParsed.suffix === 'controller' ||
        toParsed.suffix === 'terminate';
      if (usesLoopBuiltins) {
        invalidEdges.add(i);
        issues.push({
          message: `Non-loop edge[${i}] cannot use CONTROLLER/TERMINATE endpoints: ${from} -> ${to}`,
          nodes: [],
          edges: [i]
        });
      }
    }

    // Switch outgoing edge condition is mandatory.
    if (!fromParsed.suffix) {
      const fromType = typeByName[fromParsed.base];
      if (fromType === 'LogicSwitch' || fromType === 'AgentSwitch' || fromType === 'Switch') {
        const cond = typeof e?.condition === 'string' ? String(e.condition).trim() : '';
        if (!cond) {
          invalidEdges.add(i);
          invalidNodes.add(fromParsed.base);
          issues.push({
            message: `Switch edge[${i}] is missing condition (${from} -> ${to})`,
            nodes: [fromParsed.base],
            edges: [i]
          });
        }
      }
    }

    if (invalidEdges.has(i)) continue;

    validEdgeRecords.push({
      idx: i,
      from,
      to,
      scopeName: fromParent,
      scopeKind: kind
    });
    if (!fromParsed.suffix && nodeNames.has(fromParsed.base)) {
      pushOutgoing(fromParsed.base, i);
    }
  }

  // -------- Scope-level checks (ENTRY/EXIT & CONTROLLER/TERMINATE rules) --------
  /** @type {Array<string | undefined>} */
  const scopes = [undefined];
  for (const name of nodeNames) {
    const t = typeByName[name];
    if (t === 'Graph' || t === 'Subgraph' || t === 'Loop') scopes.push(name);
  }

  const scopeKey = (scopeName) => (scopeName ? `scope:${scopeName}` : 'scope:root');
  /** @type {Map<string, EdgeRecord[]>} */
  const edgesByScope = new Map();
  for (const rec of validEdgeRecords) {
    const key = scopeKey(rec.scopeName);
    const list = edgesByScope.get(key) || [];
    list.push(rec);
    edgesByScope.set(key, list);
  }

  const nodesInScope = (scopeName) => {
    /** @type {string[]} */
    const out = [];
    for (const name of nodeNames) {
      const p = parentByName[name];
      if ((p || undefined) === (scopeName || undefined)) out.push(name);
    }
    return out;
  };

  for (const scopeName of scopes) {
    const kind = scopeKind(scopeName, typeByName);
    const scopeNodes = nodesInScope(scopeName);
    const recs = edgesByScope.get(scopeKey(scopeName)) || [];

    const entryEp = scopeName ? `${scopeName}.entry` : 'entry';
    const exitEp = scopeName ? `${scopeName}.exit` : 'exit';
    const controllerEp = scopeName ? `${scopeName}.controller` : '';
    const terminateEp = scopeName ? `${scopeName}.terminate` : '';

    /** @type {Map<string, string[]>} */
    const adj = new Map();
    /** @type {Map<string, string[]>} */
    const rev = new Map();
    const addAdj = (from, to) => {
      const out = adj.get(from) || [];
      out.push(to);
      adj.set(from, out);
      const inb = rev.get(to) || [];
      inb.push(from);
      rev.set(to, inb);
    };
    for (const rec of recs) addAdj(rec.from, rec.to);

    if (kind === 'loop') {
      const hasControllerToNode = recs.some((r) => r.from === controllerEp && !!endpointToNode(r.to, nodeNames));
      const hasNodeToController = recs.some((r) => !!endpointToNode(r.from, nodeNames) && r.to === controllerEp);
      if (!hasControllerToNode) {
        if (scopeName) invalidNodes.add(scopeName);
        issues.push({
          message: `Loop "${scopeName}" must contain at least one CONTROLLER -> <node> edge`,
          nodes: scopeName ? [scopeName] : [],
          edges: []
        });
      }
      if (!hasNodeToController) {
        if (scopeName) invalidNodes.add(scopeName);
        issues.push({
          message: `Loop "${scopeName}" must contain at least one <node> -> CONTROLLER edge`,
          nodes: scopeName ? [scopeName] : [],
          edges: []
        });
      }

      const fromController = reachable(adj, controllerEp);
      const toController = reachable(rev, controllerEp);
      const toTerminate = terminateEp ? reachable(rev, terminateEp) : new Set();

      for (const nodeName of scopeNodes) {
        if (!fromController.has(nodeName)) {
          invalidNodes.add(nodeName);
          issues.push({
            message: `Loop node "${nodeName}" is not reachable from CONTROLLER`,
            nodes: [nodeName],
            edges: []
          });
        }
        if (!toController.has(nodeName) && !toTerminate.has(nodeName)) {
          invalidNodes.add(nodeName);
          issues.push({
            message: `Loop node "${nodeName}" cannot reach CONTROLLER/TERMINATE`,
            nodes: [nodeName],
            edges: []
          });
        }
      }
      continue;
    }

    // Root / Subgraph scope checks.
    const hasEntryToNode = recs.some((r) => r.from === entryEp && !!endpointToNode(r.to, nodeNames));
    const hasNodeToExit = recs.some((r) => !!endpointToNode(r.from, nodeNames) && r.to === exitEp);
    if (!hasEntryToNode) {
      issues.push({
        message: scopeName
          ? `Subgraph "${scopeName}" must contain at least one ENTRY -> <node> edge`
          : 'Root graph must contain at least one ENTRY -> <node> edge',
        nodes: scopeName ? [scopeName] : [],
        edges: []
      });
      if (scopeName) invalidNodes.add(scopeName);
    }
    if (!hasNodeToExit) {
      issues.push({
        message: scopeName
          ? `Subgraph "${scopeName}" must contain at least one <node> -> EXIT edge`
          : 'Root graph must contain at least one <node> -> EXIT edge',
        nodes: scopeName ? [scopeName] : [],
        edges: []
      });
      if (scopeName) invalidNodes.add(scopeName);
    }

    const fromEntry = reachable(adj, entryEp);
    const toExit = reachable(rev, exitEp);
    for (const nodeName of scopeNodes) {
      if (!fromEntry.has(nodeName)) {
        invalidNodes.add(nodeName);
        issues.push({
          message: `Node "${nodeName}" is not reachable from ENTRY`,
          nodes: [nodeName],
          edges: []
        });
      }
      if (!toExit.has(nodeName)) {
        invalidNodes.add(nodeName);
        issues.push({
          message: `Node "${nodeName}" cannot reach EXIT`,
          nodes: [nodeName],
          edges: []
        });
      }
    }
  }

  // -------- Switch routes consistency (optional but recommended) --------
  for (const nodeName of nodeNames) {
    const t = typeByName[nodeName];
    if (t !== 'LogicSwitch' && t !== 'AgentSwitch' && t !== 'Switch') continue;
    const node = nodeByName[nodeName];
    if (!isRecord(node)) continue;
    const routes = node.routes;
    if (!Array.isArray(routes)) continue;

    const outgoingIdxs = validOutgoingByNode.get(nodeName) || [];
    /** @type {Set<string>} */
    const routePairs = new Set();
    for (const r of routes) {
      if (!isRecord(r)) continue;
      const condition = typeof r.condition === 'string' ? r.condition.trim() : '';
      const target = typeof r.target === 'string' ? r.target.trim() : '';
      if (!condition || !target) continue;
      routePairs.add(`${condition}:::${target}`);
    }

    /** @type {Set<string>} */
    const edgePairs = new Set();
    for (const idx of outgoingIdxs) {
      const edge = edges[idx];
      const cond = typeof edge?.condition === 'string' ? String(edge.condition).trim() : '';
      const target = String(edge?.to || '').trim();
      if (!cond || !target) continue;
      edgePairs.add(`${cond}:::${target}`);
    }

    if (routePairs.size === 0 || edgePairs.size === 0) continue;
    let mismatch = routePairs.size !== edgePairs.size;
    if (!mismatch) {
      for (const p of routePairs) {
        if (!edgePairs.has(p)) {
          mismatch = true;
          break;
        }
      }
    }
    if (mismatch) {
      invalidNodes.add(nodeName);
      issues.push({
        message: `Switch "${nodeName}" routes do not match outgoing edge conditions/targets`,
        nodes: [nodeName],
        edges: outgoingIdxs
      });
    }
  }

  return { issues, invalidNodes, invalidEdges };
}
