import { buildGraphElements } from './graphElements.js';

/**
 * @param {any} graph
 * @param {{ collapsedSubgraphs?: Record<string, boolean> }} [opts]
 * @returns {Array<any>}
 */
export function buildPreviewElements(graph, opts) {
  return buildGraphElements(graph, opts);
}

export { buildGraphElements };
