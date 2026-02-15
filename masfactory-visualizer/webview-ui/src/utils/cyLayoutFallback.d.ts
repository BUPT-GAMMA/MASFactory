import type { Core } from 'cytoscape';

export type CyLayoutFallbackOpts = {
  ignoreIds?: string[];
  leafOnly?: boolean;
};

export type EnsureCyLayoutResult = {
  applied: boolean;
  method: 'breadthfirst' | 'grid' | null;
  uniquePositions: number;
};

export function uniqueNodePositionCount(cy: Core, opts?: CyLayoutFallbackOpts): number;
export function isCyLayoutDegenerate(cy: Core, opts?: CyLayoutFallbackOpts): boolean;
export function ensureCyNonDegenerateLayout(cy: Core, opts?: CyLayoutFallbackOpts): EnsureCyLayoutResult;

