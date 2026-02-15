import cytoscape from 'cytoscape';
import dagre from 'dagre';
import cytoscapeDagre from 'cytoscape-dagre';

declare global {
  // eslint-disable-next-line no-var
  var __MASFACTORY_VISUALIZER_CY_DAGRE__: boolean | undefined;
}

export function ensureCyDagreRegistered(): void {
  if (typeof window === 'undefined') return;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const w = window as any;
  if (w.__MASFACTORY_VISUALIZER_CY_DAGRE__) return;
  w.__MASFACTORY_VISUALIZER_CY_DAGRE__ = true;
  // Some versions rely on a global dagre instance.
  w.dagre = dagre;
  cytoscape.use(cytoscapeDagre as any);
}
