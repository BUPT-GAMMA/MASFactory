import type { VibeGraphDesign } from '../stores/vibe';

export type VibeV4Node = {
  /**
   * Unified graph_design spec uses `name`. Older files may still use `id`.
   */
  name?: string;
  id?: string;
  type: string;
  label: string;
  agent?: string;
  sub_graph?: VibeV4Graph;
  [k: string]: unknown;
};

export type VibeV4Edge = {
  source: string;
  target: string;
  condition?: string;
  /**
   * Edge dataflow keys mapping.
   *
   * Canonical field: `keys` (alias: `key`).
   * Shape: dict[str,str] or list[str] (normalizers may coerce values).
   */
  keys?: unknown;
  key?: unknown;
  [k: string]: unknown;
};

export type VibeV4Graph = {
  nodes: VibeV4Node[];
  edges: VibeV4Edge[];
  [k: string]: unknown;
};

export declare function isV4Graph(value: unknown): value is VibeV4Graph;
export declare function fromV4GraphDesign(graph: VibeV4Graph): VibeGraphDesign;
export declare function toV4GraphDesign(graph: VibeGraphDesign): VibeV4Graph;
