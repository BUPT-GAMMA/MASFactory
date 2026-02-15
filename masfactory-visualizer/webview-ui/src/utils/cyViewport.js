/**
 * Cytoscape viewport + selection helpers.
 *
 * Used to keep the editor stable when elements are replaced (Cytoscape resets
 * zoom/pan/selection in some cases).
 */

/**
 * @typedef {{ zoom: number; pan: { x: number; y: number } }} ViewportSnapshot
 * @typedef {{ nodes: string[]; edges: string[] }} SelectionSnapshot
 */

/**
 * @param {import('cytoscape').Core | null | undefined} cy
 * @returns {ViewportSnapshot | null}
 */
export function captureViewportSnapshot(cy) {
  if (!cy) return null;
  try {
    const zoom = cy.zoom();
    const pan = cy.pan();
    if (typeof zoom !== 'number' || !Number.isFinite(zoom)) return null;
    const panX = typeof pan?.x === 'number' && Number.isFinite(pan.x) ? pan.x : null;
    const panY = typeof pan?.y === 'number' && Number.isFinite(pan.y) ? pan.y : null;
    if (panX === null || panY === null) return null;
    return { zoom, pan: { x: panX, y: panY } };
  } catch {
    return null;
  }
}

/**
 * @param {import('cytoscape').Core | null | undefined} cy
 * @param {ViewportSnapshot | null | undefined} snap
 * @returns {void}
 */
export function restoreViewportSnapshot(cy, snap) {
  if (!cy || !snap) return;
  try {
    cy.zoom(snap.zoom);
  } catch {
    // ignore
  }
  try {
    cy.pan(snap.pan);
  } catch {
    // ignore
  }
}

/**
 * @param {import('cytoscape').Core | null | undefined} cy
 * @returns {SelectionSnapshot}
 */
export function captureSelectionSnapshot(cy) {
  if (!cy) return { nodes: [], edges: [] };
  try {
    return {
      nodes: cy
        .nodes(':selected')
        .toArray()
        .map((n) => n.id()),
      edges: cy
        .edges(':selected')
        .toArray()
        .map((e) => e.id())
    };
  } catch {
    return { nodes: [], edges: [] };
  }
}

/**
 * @param {import('cytoscape').Core | null | undefined} cy
 * @param {SelectionSnapshot | null | undefined} snap
 * @returns {void}
 */
export function restoreSelectionSnapshot(cy, snap) {
  if (!cy || !snap) return;
  try {
    for (const id of snap.nodes || []) {
      const el = cy.getElementById(String(id));
      if (el && !el.empty()) el.select();
    }
    for (const id of snap.edges || []) {
      const el = cy.getElementById(String(id));
      if (el && !el.empty()) el.select();
    }
  } catch {
    // ignore
  }
}

