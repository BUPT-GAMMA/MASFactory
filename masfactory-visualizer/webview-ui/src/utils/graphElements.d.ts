import type { ElementDefinition } from 'cytoscape';

export function buildGraphElements(
  graph: unknown,
  opts?: { collapsedSubgraphs?: Record<string, boolean> }
): ElementDefinition[];

