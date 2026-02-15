import type { ElementDefinition } from 'cytoscape';

export function buildPreviewElements(
  graph: unknown,
  opts?: { collapsedSubgraphs?: Record<string, boolean> }
): ElementDefinition[];

