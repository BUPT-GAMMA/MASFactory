/**
 * Compute a stable signature for a graph_design payload based on node ids and
 * edge pairs. Used to decide whether a document switch should trigger an
 * auto-layout.
 *
 * @param {{ Nodes?: any[]; Edges?: any[] }} graph
 * @returns {string}
 */
export function graphStructureSignature(graph) {
  const nodes = Array.isArray(graph?.Nodes) ? graph.Nodes : [];
  const edges = Array.isArray(graph?.Edges) ? graph.Edges : [];

  const nodeIds = nodes
    .map((n) => (n && typeof n === 'object' ? String(n.name || '') : ''))
    .filter(Boolean)
    .sort();

  const edgePairs = edges
    .map((e) => {
      if (!e || typeof e !== 'object') return '';
      const from = String(e.from || '');
      const to = String(e.to || '');
      if (!from || !to) return '';
      return `${from}->${to}`;
    })
    .filter(Boolean)
    .sort();

  return `${nodeIds.join('|')}||${edgePairs.join('|')}`;
}

/**
 * Decide whether the given layout should be treated as persisted for auto-layout gating.
 *
 * When we auto-generate a layout, we also record the graph signature. If the graph structure
 * changes later (e.g. nodes/edges added/removed), we treat the old auto-layout as "not persisted"
 * so a fresh auto-layout can run again — until the user manually drags nodes.
 *
 * @param {unknown} layout
 * @param {{ autoSig?: string | null; userTouched?: boolean } | null | undefined} layoutMeta
 * @param {string} nextSig
 * @returns {boolean}
 */
export function hasPersistedLayout(layout, layoutMeta, nextSig) {
  if (!layout || typeof layout !== 'object' || Array.isArray(layout)) return false;
  if (Object.keys(layout).length === 0) return false;

  if (!layoutMeta || typeof layoutMeta !== 'object') return true;

  if (layoutMeta.userTouched) return true;
  const autoSig = typeof layoutMeta.autoSig === 'string' && layoutMeta.autoSig ? layoutMeta.autoSig : null;
  if (autoSig && autoSig !== nextSig) return false;
  return true;
}

/**
 * Decide whether a graph should trigger an auto-layout.
 *
 * Rules:
 * - If a persisted layout exists, do nothing.
 * - If the graph signature did not change, do nothing.
 * - Otherwise, run the provided callback.
 *
 * @param {{ previousSig: string | null; graph: { Nodes?: any[]; Edges?: any[] }; layout?: Record<string, any>; layoutMeta?: { autoSig?: string | null; userTouched?: boolean } | null }} args
 * @param {() => void} applyLayout
 * @returns {{ nextSig: string; applied: boolean }}
 */
export function maybeAutoLayout(args, applyLayout) {
  const nextSig = graphStructureSignature(args?.graph || {});
  if (hasPersistedLayout(args?.layout, args?.layoutMeta ?? null, nextSig)) return { nextSig, applied: false };
  if (args?.previousSig && nextSig === args.previousSig) return { nextSig, applied: false };

  try {
    if (typeof applyLayout === 'function') applyLayout();
  } catch {
    // ignore
  }
  return { nextSig, applied: true };
}
