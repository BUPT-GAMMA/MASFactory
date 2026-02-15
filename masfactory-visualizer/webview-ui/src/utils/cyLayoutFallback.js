/**
 * Cytoscape layout fallbacks for the Vibe graph editor.
 *
 * The Vibe editor normally uses a smart dagre-based layout, but if that fails
 * (e.g. missing plugin, runtime error) we still want a readable graph instead
 * of every node stacking at (0,0).
 */

/**
 * @param {import('cytoscape').Core} cy
 * @param {{ ignoreIds?: string[]; leafOnly?: boolean }} [opts]
 * @returns {number}
 */
export function uniqueNodePositionCount(cy, opts) {
  if (!cy) return 0;
  const ignore = new Set(Array.isArray(opts?.ignoreIds) ? opts.ignoreIds : []);
  const leafOnly = opts?.leafOnly !== false;

  /** @type {Set<string>} */
  const seen = new Set();

  const nodes = cy.nodes().filter((n) => {
    if (!n || !n.isNode || !n.isNode()) return false;
    const id = typeof n.id === 'function' ? n.id() : '';
    if (!id) return false;
    if (ignore.has(id)) return false;
    // Ignore internal ghost nodes by convention.
    if (id.startsWith('__vibe_ghost__')) return false;
    if (leafOnly && n.isParent && n.isParent()) return false;
    return true;
  });

  nodes.forEach((n) => {
    const p = n.position();
    const x = typeof p?.x === 'number' && Number.isFinite(p.x) ? Math.round(p.x) : NaN;
    const y = typeof p?.y === 'number' && Number.isFinite(p.y) ? Math.round(p.y) : NaN;
    seen.add(`${x}:${y}`);
  });

  return seen.size;
}

/**
 * @param {import('cytoscape').Core} cy
 * @param {{ ignoreIds?: string[]; leafOnly?: boolean }} [opts]
 * @returns {boolean}
 */
export function isCyLayoutDegenerate(cy, opts) {
  if (!cy) return false;
  const ignore = new Set(Array.isArray(opts?.ignoreIds) ? opts.ignoreIds : []);
  const leafOnly = opts?.leafOnly !== false;

  const nodes = cy.nodes().filter((n) => {
    if (!n || !n.isNode || !n.isNode()) return false;
    const id = typeof n.id === 'function' ? n.id() : '';
    if (!id) return false;
    if (ignore.has(id)) return false;
    if (id.startsWith('__vibe_ghost__')) return false;
    if (leafOnly && n.isParent && n.isParent()) return false;
    return true;
  });

  if (nodes.length <= 1) return false;
  return uniqueNodePositionCount(cy, { ignoreIds: Array.from(ignore), leafOnly }) <= 1;
}

/**
 * Ensure the current Cytoscape instance has a non-degenerate layout.
 *
 * @param {import('cytoscape').Core} cy
 * @param {{ ignoreIds?: string[]; leafOnly?: boolean }} [opts]
 * @returns {{ applied: boolean; method: 'breadthfirst' | 'grid' | null; uniquePositions: number }}
 */
export function ensureCyNonDegenerateLayout(cy, opts) {
  if (!cy) return { applied: false, method: null, uniquePositions: 0 };
  if (!isCyLayoutDegenerate(cy, opts)) {
    return { applied: false, method: null, uniquePositions: uniqueNodePositionCount(cy, opts) };
  }

  const roots = (() => {
    try {
      const entry = cy.getElementById('entry');
      if (entry && !entry.empty()) return entry;
    } catch {
      // ignore
    }
    return undefined;
  })();

  try {
    cy.layout({
      name: 'breadthfirst',
      directed: true,
      roots,
      spacingFactor: 1.35,
      padding: 10,
      animate: false
    }).run();
    const unique = uniqueNodePositionCount(cy, opts);
    if (unique > 1) return { applied: true, method: 'breadthfirst', uniquePositions: unique };
  } catch {
    // ignore
  }

  try {
    cy.layout({
      name: 'grid',
      avoidOverlap: true,
      spacingFactor: 1.4,
      padding: 10,
      animate: false
    }).run();
  } catch {
    // ignore
  }

  const unique = uniqueNodePositionCount(cy, opts);
  return { applied: unique > 1, method: unique > 1 ? 'grid' : null, uniquePositions: unique };
}

