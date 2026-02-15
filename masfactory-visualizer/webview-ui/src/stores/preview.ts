import { defineStore } from 'pinia';
import type { GraphData } from '../types/graph';
import { getVsCodeApi } from '../bridge/vscode';
import type {
  AdjacencyGraphControl,
  LoopControlInfo,
  PreviewClearPayload,
  PreviewUpdatePayload,
  VisualizationSettings
} from '../types/preview';

type PreviewDocState = {
  conditions: Record<string, boolean>;
  loopIterations: Record<string, number>;
  adjacencyGraphs: Record<string, { edges: Array<{ from: number; to: number; keys?: Record<string, string> }> }>;
  edgeStyle: 'fan' | 'straight';
  collapsedSubgraphs: Record<string, boolean>;
  overlayCollapsed: Record<string, boolean>;
  positions: Record<string, { x: number; y: number }>;
  zoom: number | null;
  pan: { x: number; y: number } | null;
  templateName: string | null;
};

type PreviewPanelState = {
  documents: Record<string, PreviewDocState>;
  activeDocumentUri: string | null;
};

type PersistedStateV1 = {
  version: 1;
  preview: PreviewPanelState;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function defaultDocState(): PreviewDocState {
  return {
    conditions: {},
    loopIterations: {},
    adjacencyGraphs: {},
    edgeStyle: 'fan',
    collapsedSubgraphs: {},
    overlayCollapsed: {},
    positions: {},
    zoom: null,
    pan: null,
    templateName: null
  };
}

function defaultPanelState(): PreviewPanelState {
  return { documents: {}, activeDocumentUri: null };
}

function migrateLegacyRootState(raw: unknown): PersistedStateV1 {
  const panel = defaultPanelState();

  if (isRecord(raw)) {
    const maybePreview = raw.preview;
    if (isRecord(maybePreview)) {
      const docs = isRecord(maybePreview.documents) ? maybePreview.documents : {};
      panel.documents = docs as any;
      const active = typeof maybePreview.activeDocumentUri === 'string' ? maybePreview.activeDocumentUri : null;
      panel.activeDocumentUri = active;
      return { version: 1, preview: panel };
    }

    const docs = isRecord(raw.documents) ? raw.documents : null;
    const active =
      typeof raw.activeDocumentUri === 'string'
        ? raw.activeDocumentUri
        : typeof raw.documentUri === 'string'
          ? raw.documentUri
          : null;

    if (docs) {
      panel.documents = docs as any;
      panel.activeDocumentUri = active;
      return { version: 1, preview: panel };
    }
  }

  return { version: 1, preview: panel };
}

function readPersistedPreviewState(): PersistedStateV1 {
  const api = getVsCodeApi();
  if (!api) return { version: 1, preview: defaultPanelState() };
  const raw = api.getState();
  const migrated = migrateLegacyRootState(raw);
  try {
    api.setState(migrated);
  } catch {
    // ignore
  }
  return migrated;
}

let persistTimer: ReturnType<typeof setTimeout> | null = null;
function persistDebounced(state: PersistedStateV1, delayMs = 200): void {
  const api = getVsCodeApi();
  if (!api) return;
  if (persistTimer !== null) {
    clearTimeout(persistTimer);
    persistTimer = null;
  }
  persistTimer = setTimeout(() => {
    persistTimer = null;
    try {
      api.setState(state);
    } catch {
      // ignore
    }
  }, delayMs);
}

export const usePreviewStore = defineStore('preview', {
  state: () => {
    const persisted = readPersistedPreviewState();
    return {
      persisted,
      graph: null as GraphData | null,
      settings: {} as VisualizationSettings,
      documentUri: persisted.preview.activeDocumentUri as string | null,
      conditionVariables: [] as string[],
      loopControls: {} as Record<string, LoopControlInfo>,
      loopWarnings: [] as string[],
      loopIterationsFromExtension: {} as Record<string, number>,
      adjacencyGraphControls: {} as Record<string, AdjacencyGraphControl>,
      clearReason: null as string | null
    };
  },
  getters: {
    currentDocState(state): PreviewDocState | null {
      const uri = state.documentUri;
      if (!uri) return null;
      return state.persisted.preview.documents[uri] ?? null;
    }
  },
  actions: {
    persist(): void {
      persistDebounced(this.persisted);
    },
    ensureDocState(uri: string): PreviewDocState {
      const docs = this.persisted.preview.documents;
      if (!docs[uri]) {
        docs[uri] = defaultDocState();
        return docs[uri]!;
      }
      const st = docs[uri] as any;
      if (!st.conditions) st.conditions = {};
      if (!st.loopIterations) st.loopIterations = {};
      if (!st.adjacencyGraphs) st.adjacencyGraphs = {};
      if (!st.edgeStyle) st.edgeStyle = 'fan';
      if (!st.collapsedSubgraphs) st.collapsedSubgraphs = {};
      if (!st.overlayCollapsed) st.overlayCollapsed = {};
      if (!st.positions) st.positions = {};
      if (st.zoom === undefined) st.zoom = null;
      if (st.pan === undefined) st.pan = null;
      if (st.templateName === undefined) st.templateName = null;
      return docs[uri]!;
    },
    setActiveDocument(uri: string | null): void {
      this.documentUri = uri;
      this.persisted.preview.activeDocumentUri = uri;
      if (uri) this.ensureDocState(uri);
      persistDebounced(this.persisted);
    },
    resetCurrentDocumentState(): void {
      const uri = this.documentUri;
      if (!uri) return;
      delete this.persisted.preview.documents[uri];
      this.ensureDocState(uri);
      persistDebounced(this.persisted);
    },
    setConditions(conditions: Record<string, boolean>): void {
      const uri = this.documentUri;
      if (!uri) return;
      const doc = this.ensureDocState(uri);
      doc.conditions = { ...conditions };
      persistDebounced(this.persisted);
    },
    setLoopIterations(loopIterations: Record<string, number>): void {
      const uri = this.documentUri;
      if (!uri) return;
      const doc = this.ensureDocState(uri);
      doc.loopIterations = { ...loopIterations };
      persistDebounced(this.persisted);
    },
    setAdjacencyGraphEdges(
      graphVariable: string,
      edges: Array<{ from: number; to: number; keys?: Record<string, string> }>
    ): void {
      const uri = this.documentUri;
      if (!uri) return;
      const doc = this.ensureDocState(uri);
      if (!doc.adjacencyGraphs) doc.adjacencyGraphs = {};
      doc.adjacencyGraphs[graphVariable] = { edges };
      persistDebounced(this.persisted);
    },
    setEdgeStyle(style: 'fan' | 'straight'): void {
      const uri = this.documentUri;
      if (!uri) return;
      const doc = this.ensureDocState(uri);
      doc.edgeStyle = style;
      persistDebounced(this.persisted);
    },
    setTemplateName(templateName: string | null): void {
      const uri = this.documentUri;
      if (!uri) return;
      const doc = this.ensureDocState(uri);
      const next = typeof templateName === 'string' ? templateName.trim() : '';
      doc.templateName = next ? next : null;
      persistDebounced(this.persisted);
    },
    setCollapsedSubgraph(nodeId: string, collapsed: boolean): void {
      const uri = this.documentUri;
      if (!uri) return;
      const doc = this.ensureDocState(uri);
      if (!doc.collapsedSubgraphs) doc.collapsedSubgraphs = {};
      if (collapsed) doc.collapsedSubgraphs[nodeId] = true;
      else delete doc.collapsedSubgraphs[nodeId];
      persistDebounced(this.persisted);
    },
    setOverlayCollapsed(graphId: string, collapsed: boolean): void {
      const uri = this.documentUri;
      if (!uri) return;
      const doc = this.ensureDocState(uri);
      if (!doc.overlayCollapsed) doc.overlayCollapsed = {};
      if (collapsed) doc.overlayCollapsed[graphId] = true;
      else delete doc.overlayCollapsed[graphId];
      persistDebounced(this.persisted);
    },
    setViewport(zoom: number, pan: { x: number; y: number }): void {
      const uri = this.documentUri;
      if (!uri) return;
      const doc = this.ensureDocState(uri);
      doc.zoom = zoom;
      doc.pan = { x: pan.x, y: pan.y };
      persistDebounced(this.persisted);
    },
    setNodePosition(nodeId: string, pos: { x: number; y: number }): void {
      const uri = this.documentUri;
      if (!uri) return;
      const doc = this.ensureDocState(uri);
      if (!doc.positions) doc.positions = {};
      doc.positions[nodeId] = { x: pos.x, y: pos.y };
      persistDebounced(this.persisted);
    },
    mergeNodePositions(positions: Record<string, { x: number; y: number }>, opts?: { overwrite?: boolean }): void {
      const uri = this.documentUri;
      if (!uri) return;
      const doc = this.ensureDocState(uri);
      if (!doc.positions) doc.positions = {};
      const overwrite = !!opts?.overwrite;
      for (const [nodeId, pos] of Object.entries(positions)) {
        if (!overwrite && doc.positions[nodeId]) continue;
        doc.positions[nodeId] = { x: pos.x, y: pos.y };
      }
      persistDebounced(this.persisted);
    },
    applyUpdate(payload: PreviewUpdatePayload): void {
      const uri = payload.documentUri;
      if (!uri) return;

      this.setActiveDocument(uri);
      const docState = this.ensureDocState(uri);

      const conditionVariables = Array.isArray(payload.conditionVariables)
        ? payload.conditionVariables.filter((x) => typeof x === 'string' && x)
        : [];
      const loopControls = payload.loopControls && typeof payload.loopControls === 'object' ? payload.loopControls : {};
      const loopWarnings = Array.isArray(payload.loopWarnings) ? payload.loopWarnings.filter((x) => typeof x === 'string') : [];
      const loopIterations = payload.loopIterations && typeof payload.loopIterations === 'object' ? payload.loopIterations : {};
      const adjacencyGraphControls =
        payload.adjacencyGraphControls && typeof payload.adjacencyGraphControls === 'object' ? payload.adjacencyGraphControls : {};

      // Merge condition state.
      const nextConditions: Record<string, boolean> = {};
      for (const cond of conditionVariables) {
        const saved = docState.conditions?.[cond];
        nextConditions[cond] = saved === false || saved === ('false' as any) ? false : true;
      }
      docState.conditions = nextConditions;

      // Merge loop iterations state.
      const mergedIterations: Record<string, number> = {};
      for (const [loopId, info] of Object.entries(loopControls)) {
        const fromState = docState.loopIterations?.[loopId];
        if (fromState !== undefined) {
          mergedIterations[loopId] = Number(fromState);
        } else if (loopIterations[loopId] !== undefined) {
          const numeric = Number(loopIterations[loopId]);
          mergedIterations[loopId] = Number.isFinite(numeric) ? numeric : info.defaultIterations ?? 1;
        } else {
          mergedIterations[loopId] = info.defaultIterations ?? 1;
        }
      }
      docState.loopIterations = mergedIterations;

      if (!docState.adjacencyGraphs) docState.adjacencyGraphs = {};
      for (const graphVariable of Object.keys(adjacencyGraphControls)) {
        if (!docState.adjacencyGraphs[graphVariable]) docState.adjacencyGraphs[graphVariable] = { edges: [] };
      }

      if (!docState.edgeStyle) docState.edgeStyle = 'fan';

      // Standalone NodeTemplate selection (if present).
      const candidatesRaw = (payload.data as any)?.templateCandidates;
      const candidates = Array.isArray(candidatesRaw)
        ? candidatesRaw.filter((x: any) => typeof x === 'string' && x.trim()).map((x: any) => String(x).trim())
        : [];
      const selectedRaw = (payload.data as any)?.selectedTemplate;
      const selected =
        typeof selectedRaw === 'string' && selectedRaw.trim()
          ? selectedRaw.trim()
          : candidates.length > 0
            ? candidates[candidates.length - 1]
            : null;

      if (candidates.length > 0) {
        // Keep docState in sync with extension selection.
        docState.templateName = selected;
      } else if (docState.templateName) {
        // If the file no longer has templates, clear stored selection.
        docState.templateName = null;
      }

      this.graph = payload.data || null;
      this.settings = payload.settings || {};
      this.conditionVariables = conditionVariables;
      this.loopControls = loopControls;
      this.loopWarnings = loopWarnings;
      this.loopIterationsFromExtension = loopIterations;
      this.adjacencyGraphControls = adjacencyGraphControls;
      this.clearReason = null;

      persistDebounced(this.persisted);
    },
    applyClear(payload: PreviewClearPayload): void {
      this.graph = null;
      this.clearReason = payload.reason || 'No graph to display';
    }
  }
});
