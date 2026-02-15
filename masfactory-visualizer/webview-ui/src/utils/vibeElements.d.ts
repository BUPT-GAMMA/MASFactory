import type { ElementDefinition } from 'cytoscape';
import type { VibeGraphDesign } from '../stores/vibe';

export declare function buildVibeElements(
  graph: VibeGraphDesign,
  positions: Record<string, { x: number; y: number }>,
  invalidNodes: Set<string>,
  invalidEdges: Set<number>
): ElementDefinition[];

