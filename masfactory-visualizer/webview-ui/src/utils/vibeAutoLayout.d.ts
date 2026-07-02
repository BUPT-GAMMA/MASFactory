import type { VibeGraphDesign, VibeLayout, VibeLayoutMeta } from '../stores/vibe';

export function graphStructureSignature(graph: VibeGraphDesign): string;

export function maybeAutoLayout(
  args: { previousSig: string | null; graph: VibeGraphDesign; layout?: VibeLayout; layoutMeta?: VibeLayoutMeta | null },
  applyLayout: () => void
): { nextSig: string; applied: boolean };
