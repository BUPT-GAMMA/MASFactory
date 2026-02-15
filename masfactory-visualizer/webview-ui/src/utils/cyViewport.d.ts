import type { Core } from 'cytoscape';

export type ViewportSnapshot = { zoom: number; pan: { x: number; y: number } };
export type SelectionSnapshot = { nodes: string[]; edges: string[] };

export declare function captureViewportSnapshot(cy: Core | null | undefined): ViewportSnapshot | null;
export declare function restoreViewportSnapshot(
  cy: Core | null | undefined,
  snap: ViewportSnapshot | null | undefined
): void;

export declare function captureSelectionSnapshot(cy: Core | null | undefined): SelectionSnapshot;
export declare function restoreSelectionSnapshot(
  cy: Core | null | undefined,
  snap: SelectionSnapshot | null | undefined
): void;

