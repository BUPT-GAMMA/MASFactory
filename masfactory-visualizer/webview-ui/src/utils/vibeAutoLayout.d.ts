import type { VibeGraphDesign, VibeLayout } from '../stores/vibe';

export function graphStructureSignature(graph: VibeGraphDesign): string;

export function maybeAutoLayout(
  args: { previousSig: string | null; graph: VibeGraphDesign; layout?: VibeLayout },
  applyLayout: () => void
): { nextSig: string; applied: boolean };

