import { defineStore } from 'pinia';
import { postMessage } from '../bridge/vscode';
import type {
  VibeDocState,
  VibeEdgeSpec,
  VibeGraphDesign,
  VibeHistorySnapshot,
  VibeLayout,
  VibeLayoutMeta,
  VibeNodeSpec,
  VibeNodeType
} from './vibeTypes';
import {
  allowedKeysForType,
  deepClone,
  extractGraphDesign,
  graphSignature,
  isInternalNodeId,
  layoutSignature,
  normalizeGraphDesign,
  parentOfEndpoint,
  pickFields,
  safeJsonParse,
  toV4GraphDesign,
  setAtPath
} from './vibeModel';

const COALESCE_UNTIL_BY_URI = new Map<string, number>();
const APPLYING_HISTORY = new Set<string>();

export const useVibeStore = defineStore('vibe', {
  state: () => ({
    docs: {} as Record<string, VibeDocState>,
    activeUri: null as string | null,
    layouts: {} as Record<string, VibeLayout>,
    layoutMeta: {} as Record<string, VibeLayoutMeta>,
    history: {} as Record<string, { past: VibeHistorySnapshot[]; future: VibeHistorySnapshot[] }>
  }),
  getters: {
    activeDoc(state): VibeDocState | null {
      return state.activeUri ? state.docs[state.activeUri] || null : null;
    },
    activeGraph(state): VibeGraphDesign | null {
      const uri = state.activeUri;
      if (!uri) return null;
      const doc = state.docs[uri];
      if (!doc) return null;
      return doc.dirtyGraph || doc.graph;
    },
    activeLayout(state): VibeLayout {
      const uri = state.activeUri;
      if (!uri) return {};
      return state.layouts[uri] || {};
    },
    activeLayoutMeta(state): VibeLayoutMeta | null {
      const uri = state.activeUri;
      if (!uri) return null;
      return state.layoutMeta[uri] || { autoSig: null, userTouched: false };
    },
    canUndo(state): (uri: string) => boolean {
      return (uri: string) => {
        const h = state.history[uri];
        return !!h && Array.isArray(h.past) && h.past.length > 0;
      };
    },
    canRedo(state): (uri: string) => boolean {
      return (uri: string) => {
        const h = state.history[uri];
        return !!h && Array.isArray(h.future) && h.future.length > 0;
      };
    }
  },
  actions: {
    clearHistory(uri: string): void {
      if (!uri) return;
      this.history = { ...this.history, [uri]: { past: [], future: [] } };
      COALESCE_UNTIL_BY_URI.delete(uri);
    },

    // Record a pre-mutation undo point (snapshot current state before applying changes).
    recordUndoPoint(uri: string, opts?: { coalesceMs?: number; kind?: 'graph' | 'layout' }): void {
      if (!uri) return;
      if (APPLYING_HISTORY.has(uri)) return;
      const doc = this.docs[uri];
      if (!doc || !doc.graph) return;

      const now = Date.now();
      const coalesceMs = typeof opts?.coalesceMs === 'number' && opts.coalesceMs > 0 ? opts.coalesceMs : 0;
      const until = COALESCE_UNTIL_BY_URI.get(uri) || 0;
      if (coalesceMs > 0 && now < until) return;

      const layout = this.layouts[uri] || {};
      const kind = opts?.kind === 'layout' ? 'layout' : 'graph';
      const effectiveGraph = doc.dirtyGraph || doc.graph;
      const snap: VibeHistorySnapshot = {
        graph: kind === 'graph' ? deepClone(effectiveGraph) : undefined,
        layout: deepClone(layout),
        ts: now
      };

      const prev = this.history[uri] || { past: [], future: [] };
      const past = Array.isArray(prev.past) ? prev.past.slice() : [];
      const future: VibeHistorySnapshot[] = [];

      const last = past[past.length - 1];
      if (last) {
        const sameGraph =
          (!!last.graph && !!snap.graph && graphSignature(last.graph) === graphSignature(snap.graph)) ||
          (!last.graph && !snap.graph);
        const sameLayout =
          (!!last.layout && !!snap.layout && layoutSignature(last.layout) === layoutSignature(snap.layout)) ||
          (!last.layout && !snap.layout);
        if (sameGraph && sameLayout) {
          COALESCE_UNTIL_BY_URI.set(uri, now + coalesceMs);
          this.history = { ...this.history, [uri]: { past, future } };
          return;
        }
      }

      past.push(snap);
      if (past.length > 20) past.splice(0, past.length - 20);
      this.history = { ...this.history, [uri]: { past, future } };
      COALESCE_UNTIL_BY_URI.set(uri, now + coalesceMs);
    },

    applySnapshot(uri: string, snap: VibeHistorySnapshot): void {
      const doc = this.docs[uri];
      if (!doc || !doc.graph) return;
      APPLYING_HISTORY.add(uri);
      try {
        if (snap.layout) {
          const nextLayout = deepClone(snap.layout || {});
          this.layouts = { ...this.layouts, [uri]: nextLayout };
        }

        if (snap.graph) {
          const baseSig = doc.baseGraphSig || graphSignature(doc.graph);
          const nextGraph = deepClone(snap.graph);
          const nextSig = graphSignature(nextGraph);
          const isDirty = nextSig !== baseSig;

          this.docs = {
            ...this.docs,
            [uri]: {
              ...doc,
              dirtyGraph: isDirty ? nextGraph : null,
              dirty: isDirty,
              saving: false,
              saveError: null
            }
          };
        } else {
          // Layout-only snapshots should not affect dirty state.
          this.docs = {
            ...this.docs,
            [uri]: {
              ...doc,
              saving: false
            }
          };
        }
      } finally {
        APPLYING_HISTORY.delete(uri);
      }
    },

    undo(uri: string): void {
      if (!uri) return;
      const doc = this.docs[uri];
      if (!doc || !doc.graph) return;
      const h = this.history[uri];
      if (!h || !Array.isArray(h.past) || h.past.length === 0) return;

      const effectiveGraph = doc.dirtyGraph || doc.graph;
      const past = h.past.slice();
      const future = Array.isArray(h.future) ? h.future.slice() : [];
      const prev = past.pop()!;
      const currentSnap: VibeHistorySnapshot = {
        graph: prev.graph ? deepClone(effectiveGraph) : undefined,
        layout: prev.layout ? deepClone(this.layouts[uri] || {}) : undefined,
        ts: Date.now()
      };
      future.push(currentSnap);
      if (future.length > 20) future.splice(0, future.length - 20);

      this.history = { ...this.history, [uri]: { past, future } };
      this.applySnapshot(uri, prev);
      COALESCE_UNTIL_BY_URI.delete(uri);
    },

    redo(uri: string): void {
      if (!uri) return;
      const doc = this.docs[uri];
      if (!doc || !doc.graph) return;
      const h = this.history[uri];
      if (!h || !Array.isArray(h.future) || h.future.length === 0) return;

      const effectiveGraph = doc.dirtyGraph || doc.graph;
      const past = Array.isArray(h.past) ? h.past.slice() : [];
      const future = h.future.slice();
      const next = future.pop()!;
      const currentSnap: VibeHistorySnapshot = {
        graph: next.graph ? deepClone(effectiveGraph) : undefined,
        layout: next.layout ? deepClone(this.layouts[uri] || {}) : undefined,
        ts: Date.now()
      };
      past.push(currentSnap);
      if (past.length > 20) past.splice(0, past.length - 20);

      this.history = { ...this.history, [uri]: { past, future } };
      this.applySnapshot(uri, next);
      COALESCE_UNTIL_BY_URI.delete(uri);
    },

    ingestDocument(payload: { uri: string; fileName: string; text: string }): boolean {
      const uri = String(payload.uri || '');
      if (!uri) return false;
      const fileName = String(payload.fileName || '');
      const text = String(payload.text ?? '');

      const prev = this.docs[uri];
      const wasDirty = !!prev?.dirty;

      const parsed = safeJsonParse(text);
      if (parsed.error) {
        if (prev?.graph && prev.sourceText !== text) this.clearHistory(uri);
        this.docs = {
          ...this.docs,
          [uri]: {
            uri,
            fileName,
            sourceText: text,
            graph: null,
            graphLocator: null,
            baseGraphSig: prev?.baseGraphSig ?? null,
            parseError: parsed.error,
            dirtyGraph: wasDirty ? prev?.dirtyGraph ?? null : null,
            dirty: wasDirty,
            saving: false,
            saveError: null
          }
        };
        return false;
      }

      const extracted = extractGraphDesign(parsed.value);
      if (!extracted) {
        if (prev?.graph && prev.sourceText !== text) this.clearHistory(uri);
        this.docs = {
          ...this.docs,
          [uri]: {
            uri,
            fileName,
            sourceText: text,
            graph: null,
            graphLocator: null,
            baseGraphSig: null,
            parseError: null,
            dirtyGraph: null,
            dirty: false,
            saving: false,
            saveError: null
          }
        };
        return false;
      }

      const normalized = normalizeGraphDesign(extracted.graph);
      const baseGraphSig = graphSignature(normalized);

      // If the file changed externally while we had unsaved edits, drop the dirty state
      // and rebase on the on-disk content to avoid producing an inconsistent merge.
      const shouldDropDirty = wasDirty && prev?.sourceText !== text;
      if (shouldDropDirty) this.clearHistory(uri);
      if (!this.history[uri]) this.clearHistory(uri);

      this.docs = {
        ...this.docs,
        [uri]: {
          uri,
          fileName,
          sourceText: text,
          graph: normalized,
          graphLocator: extracted.locator,
          baseGraphSig,
          parseError: null,
          dirtyGraph: shouldDropDirty ? null : prev?.dirtyGraph ?? null,
          dirty: shouldDropDirty ? false : wasDirty,
          saving: false,
          saveError: null
        }
      };

      this.activeUri = uri;
      if (!this.layouts[uri]) {
        this.layouts = { ...this.layouts, [uri]: {} };
      }
      if (!this.layoutMeta[uri]) {
        this.layoutMeta = { ...this.layoutMeta, [uri]: { autoSig: null, userTouched: false } };
      }

      return true;
    },

    setActive(uri: string | null): void {
      this.activeUri = uri;
    },

    markLayoutTouched(uri: string): void {
      if (!uri) return;
      const prev = this.layoutMeta[uri] || { autoSig: null, userTouched: false };
      if (prev.userTouched) return;
      this.layoutMeta = { ...this.layoutMeta, [uri]: { ...prev, userTouched: true } };
    },

    updateLayout(uri: string, nodeId: string, pos: { x: number; y: number }): void {
      if (!uri || !nodeId) return;
      const current = this.layouts[uri] || {};
      const prev = current[nodeId];
      if (prev && prev.x === pos.x && prev.y === pos.y) return;
      this.recordUndoPoint(uri, { coalesceMs: 350, kind: 'layout' });
      this.markLayoutTouched(uri);
      this.layouts = {
        ...this.layouts,
        [uri]: { ...current, [nodeId]: { x: pos.x, y: pos.y } }
      };
    },

    applyAutoLayout(uri: string, layout: VibeLayout, sig: string): void {
      if (!uri) return;
      const next: VibeLayout = {};
      if (layout && typeof layout === 'object') {
        for (const [id, p] of Object.entries(layout)) {
          const x = typeof p?.x === 'number' && Number.isFinite(p.x) ? p.x : null;
          const y = typeof p?.y === 'number' && Number.isFinite(p.y) ? p.y : null;
          if (x === null || y === null) continue;
          next[id] = { x, y };
        }
      }

      const current = this.layouts[uri] || {};
      // Cheap equality check: if key count differs, it's changed; otherwise compare JSON signatures.
      const sameKeys = Object.keys(current).length === Object.keys(next).length;
      if (sameKeys) {
        const curSig = layoutSignature(current);
        const nextSig = layoutSignature(next);
        if (curSig === nextSig) {
          const prevMeta = this.layoutMeta[uri] || { autoSig: null, userTouched: false };
          if (prevMeta.autoSig !== sig || prevMeta.userTouched) {
            this.layoutMeta = { ...this.layoutMeta, [uri]: { autoSig: sig, userTouched: false } };
          }
          return;
        }
      }

      this.recordUndoPoint(uri, { coalesceMs: 350, kind: 'layout' });
      this.layouts = { ...this.layouts, [uri]: next };
      this.layoutMeta = { ...this.layoutMeta, [uri]: { autoSig: sig || null, userTouched: false } };
    },

    setDirtyGraph(uri: string, graph: VibeGraphDesign): void {
      const doc = this.docs[uri];
      if (!doc) return;
      // Update dirty status based on file baseline signature.
      const baseSig = doc.baseGraphSig || (doc.graph ? graphSignature(doc.graph) : null);
      const nextSig = graphSignature(graph);
      const isDirty = baseSig ? nextSig !== baseSig : true;
      this.docs = {
        ...this.docs,
        [uri]: {
          ...doc,
          dirtyGraph: isDirty ? graph : null,
          dirty: isDirty
        }
      };
    },

    ensureMutableGraph(uri: string): VibeGraphDesign | null {
      const doc = this.docs[uri];
      if (!doc || !doc.graph) return null;
      if (doc.dirtyGraph) return doc.dirtyGraph;
      const cloned = deepClone(doc.graph);
      this.setDirtyGraph(uri, cloned);
      return cloned;
    },

    requestSave(uri: string): void {
      const doc = this.docs[uri];
      if (!doc) return;
      const graph = doc.dirtyGraph || doc.graph;
      if (!graph) return;
      this.docs = {
        ...this.docs,
        [uri]: { ...doc, saving: true, saveError: null }
      };
      const locator = doc.graphLocator;
      const v4 = toV4GraphDesign(graph);
      let text = JSON.stringify(v4, null, 2);
      if (locator) {
        const rootParsed = safeJsonParse(doc.sourceText || '');
        if (!rootParsed.error) {
          const rootValue = rootParsed.value;
          if (locator.path.length === 0) {
            if (locator.asString) {
              const inner = JSON.stringify(v4, null, 2);
              text = JSON.stringify(inner, null, 2);
            } else {
              text = JSON.stringify(v4, null, 2);
            }
          } else if (rootValue && typeof rootValue === 'object') {
            const nextValue = locator.asString ? JSON.stringify(v4, null, 2) : v4;
            if (!setAtPath(rootValue, locator.path, nextValue)) {
              this.docs = {
                ...this.docs,
                [uri]: {
                  ...doc,
                  saving: false,
                  saveError: 'Unable to locate embedded graph_design in the current document. Click Reload, then try saving again.'
                }
              };
              return;
            }
            text = JSON.stringify(rootValue, null, 2);
          } else {
            this.docs = {
              ...this.docs,
              [uri]: {
                ...doc,
                saving: false,
                saveError:
                  'Cannot update embedded graph_design because the current document is not a JSON object/array. Click Reload, then try again.'
              }
            };
            return;
          }
        }
      }
      postMessage({ type: 'vibeSave', documentUri: uri, text });
    },

    discardEdits(uri: string): void {
      const doc = this.docs[uri];
      if (!doc) return;
      this.docs = {
        ...this.docs,
        [uri]: {
          ...doc,
          dirtyGraph: null,
          dirty: false,
          saving: false,
          saveError: null
        }
      };
    },

    requestReload(uri: string): void {
      if (!uri) return;
      this.discardEdits(uri);
      this.clearHistory(uri);
      postMessage({ type: 'vibeReload', documentUri: uri });
    },

    applySaveResult(payload: { uri: string; ok: boolean; error?: string | null }): void {
      const uri = String(payload.uri || '');
      const doc = this.docs[uri];
      if (!doc) return;
      if (!payload.ok) {
        this.docs = {
          ...this.docs,
          [uri]: { ...doc, saving: false, saveError: payload.error || 'Save failed' }
        };
        return;
      }
      this.docs = {
        ...this.docs,
        [uri]: { ...doc, saving: false, saveError: null, dirty: false, dirtyGraph: null }
      };
    },

    addNode(uri: string, spec: VibeNodeSpec, position?: { x: number; y: number }): void {
      this.recordUndoPoint(uri);
      const graph = this.ensureMutableGraph(uri);
      if (!graph) return;
      graph.Nodes = [...(graph.Nodes || []), spec];
      this.setDirtyGraph(uri, graph);
      if (position) {
        this.markLayoutTouched(uri);
        const current = this.layouts[uri] || {};
        this.layouts = {
          ...this.layouts,
          [uri]: { ...current, [spec.name]: { x: position.x, y: position.y } }
        };
      }
    },

    addEdge(uri: string, edge: VibeEdgeSpec): void {
      this.recordUndoPoint(uri);
      const graph = this.ensureMutableGraph(uri);
      if (!graph) return;
      graph.Edges = [...(graph.Edges || []), edge];
      this.setDirtyGraph(uri, graph);
    },

    updateNodeSpec(uri: string, nodeName: string, nextSpec: VibeNodeSpec): void {
      if (!uri || !nodeName) return;
      this.recordUndoPoint(uri);
      const graph = this.ensureMutableGraph(uri);
      if (!graph) return;
      const nodes = Array.isArray(graph.Nodes) ? graph.Nodes.slice() : [];
      const idx = nodes.findIndex((n: any) => String(n?.name || '') === nodeName);
      if (idx === -1) return;
      const prev = nodes[idx] as any;
      const next = { ...prev, ...nextSpec } as VibeNodeSpec;
      nodes[idx] = next;
      graph.Nodes = nodes;
      this.setDirtyGraph(uri, graph);
    },

    updateEdgeAt(uri: string, edgeIndex: number, nextEdge: VibeEdgeSpec): void {
      if (!uri) return;
      this.recordUndoPoint(uri);
      const graph = this.ensureMutableGraph(uri);
      if (!graph) return;
      const edges = Array.isArray(graph.Edges) ? graph.Edges.slice() : [];
      if (edgeIndex < 0 || edgeIndex >= edges.length) return;
      edges[edgeIndex] = nextEdge as any;
      graph.Edges = edges;
      this.setDirtyGraph(uri, graph);
    },

    deleteNode(uri: string, nodeName: string): void {
      this.removeNode(uri, nodeName);
    },

    deleteEdge(uri: string, edgeIndex: number): void {
      this.removeEdge(uri, edgeIndex);
    },

    removeEdge(uri: string, edgeIndex: number): void {
      this.recordUndoPoint(uri);
      const graph = this.ensureMutableGraph(uri);
      if (!graph) return;
      const edges = Array.isArray(graph.Edges) ? graph.Edges.slice() : [];
      if (edgeIndex < 0 || edgeIndex >= edges.length) return;
      edges.splice(edgeIndex, 1);
      graph.Edges = edges;
      this.setDirtyGraph(uri, graph);
    },

    updateEdge(uri: string, edgeIndex: number, patch: Record<string, unknown>): void {
      this.recordUndoPoint(uri);
      const graph = this.ensureMutableGraph(uri);
      if (!graph) return;
      const edges = Array.isArray(graph.Edges) ? graph.Edges.slice() : [];
      if (edgeIndex < 0 || edgeIndex >= edges.length) return;
      const current = edges[edgeIndex];
      edges[edgeIndex] = { ...(current as any), ...patch } as any;
      graph.Edges = edges;
      this.setDirtyGraph(uri, graph);
    },

    removeNode(uri: string, nodeName: string): void {
      this.recordUndoPoint(uri);
      const graph = this.ensureMutableGraph(uri);
      if (!graph) return;
      const nodes = Array.isArray(graph.Nodes) ? graph.Nodes.slice() : [];
      const idx = nodes.findIndex((n: any) => String(n?.name || '') === nodeName);
      if (idx === -1) return;
      nodes.splice(idx, 1);
      graph.Nodes = nodes;

      // Remove edges connected to this node.
      const edges = Array.isArray(graph.Edges) ? graph.Edges : [];
      graph.Edges = edges.filter((e: any) => String(e?.from || '') !== nodeName && String(e?.to || '') !== nodeName);

      // Remove layout entries for node + endpoints.
      const curLayout = this.layouts[uri] || {};
      const nextLayout = { ...curLayout };
      delete nextLayout[nodeName];
      delete nextLayout[`${nodeName}.entry`];
      delete nextLayout[`${nodeName}.exit`];
      delete nextLayout[`${nodeName}.controller`];
      delete nextLayout[`${nodeName}.terminate`];
      this.layouts = { ...this.layouts, [uri]: nextLayout };

      this.setDirtyGraph(uri, graph);
    },

    renameNode(uri: string, prevName: string, nextName: string): boolean {
      if (!prevName || !nextName || prevName === nextName) return false;
      this.recordUndoPoint(uri);
      const graph = this.ensureMutableGraph(uri);
      if (!graph) return false;
      const nodes = Array.isArray(graph.Nodes) ? graph.Nodes.slice() : [];
      const idx = nodes.findIndex((n: any) => String(n?.name || '') === prevName);
      if (idx === -1) return false;
      if (nodes.some((n: any) => String(n?.name || '') === nextName)) return false;
      const prevNode: any = nodes[idx];
      nodes[idx] = { ...prevNode, name: nextName };
      graph.Nodes = nodes;

      // Update edges referencing the node or its internal endpoints.
      const edges = Array.isArray(graph.Edges) ? graph.Edges.slice() : [];
      graph.Edges = edges.map((e: any) => {
        const from = String(e?.from || '');
        const to = String(e?.to || '');
        const nextFrom = from === prevName ? nextName : from.replace(`${prevName}.`, `${nextName}.`);
        const nextTo = to === prevName ? nextName : to.replace(`${prevName}.`, `${nextName}.`);
        if (nextFrom === from && nextTo === to) return e;
        return { ...e, from: nextFrom, to: nextTo };
      });

      // Update layout map keys.
      const curLayout = this.layouts[uri] || {};
      const nextLayout: VibeLayout = {};
      for (const [k, v] of Object.entries(curLayout)) {
        if (k === prevName) nextLayout[nextName] = v;
        else if (k.startsWith(`${prevName}.`)) nextLayout[k.replace(`${prevName}.`, `${nextName}.`)] = v;
        else nextLayout[k] = v;
      }
      this.layouts = { ...this.layouts, [uri]: nextLayout };

      this.setDirtyGraph(uri, graph);
      return true;
    },

    changeNodeType(uri: string, nodeName: string, nextType: VibeNodeType): void {
      this.recordUndoPoint(uri);
      const graph = this.ensureMutableGraph(uri);
      if (!graph) return;
      const nodes = Array.isArray(graph.Nodes) ? graph.Nodes.slice() : [];
      const idx = nodes.findIndex((n: any) => String(n?.name || '') === nodeName);
      if (idx === -1) return;
      const prev: any = nodes[idx];
      const prevType = String(prev?.type || '');
      const type = String(nextType || '');
      if (!type || prevType === type) return;

      const allowed = allowedKeysForType(type);
      const cleaned = pickFields({ ...prev, type }, allowed);
      nodes[idx] = cleaned as any;
      graph.Nodes = nodes;
      this.setDirtyGraph(uri, graph);
    },

    updateNodeParent(uri: string, nodeName: string, nextParent?: string): void {
      this.recordUndoPoint(uri);
      const graph = this.ensureMutableGraph(uri);
      if (!graph) return;
      const nodes = Array.isArray(graph.Nodes) ? graph.Nodes.slice() : [];
      const idx = nodes.findIndex((n: any) => String(n?.name || '') === nodeName);
      if (idx === -1) return;
      const prev: any = nodes[idx];
      const normalized = typeof nextParent === 'string' && nextParent.trim() ? nextParent.trim() : undefined;
      if (prev.parent === normalized || (!prev.parent && !normalized)) return;
      nodes[idx] = { ...prev, parent: normalized };
      graph.Nodes = nodes;

      // When moving nodes into/out of subgraphs, any edges crossing scope are invalid in Vibe.
      const parentByName: Record<string, string | undefined> = {};
      for (const n of nodes) {
        const name = String((n as any)?.name || '');
        if (!name) continue;
        const parent = typeof (n as any)?.parent === 'string' && (n as any).parent.trim() ? (n as any).parent.trim() : undefined;
        parentByName[name] = parent;
      }

      const edges = Array.isArray(graph.Edges) ? graph.Edges.slice() : [];
      graph.Edges = edges.filter((e: any) => {
        const from = String(e?.from || '');
        const to = String(e?.to || '');
        const fromParent = parentOfEndpoint(from, parentByName);
        const toParent = parentOfEndpoint(to, parentByName);
        if (fromParent !== toParent) return false;
        return true;
      });

      this.setDirtyGraph(uri, graph);
    },

    updateNodeField(uri: string, nodeName: string, field: string, value: unknown): void {
      if (!uri || !nodeName || !field) return;
      this.recordUndoPoint(uri);
      const graph = this.ensureMutableGraph(uri);
      if (!graph) return;
      const nodes = Array.isArray(graph.Nodes) ? graph.Nodes.slice() : [];
      const idx = nodes.findIndex((n: any) => String(n?.name || '') === nodeName);
      if (idx === -1) return;
      const prev: any = nodes[idx];
      const type = String(prev?.type || 'Agent') as VibeNodeType;
      const allowed = allowedKeysForType(type);
      if (!allowed.has(field)) return;
      nodes[idx] = { ...prev, [field]: value } as any;
      graph.Nodes = nodes;
      this.setDirtyGraph(uri, graph);
    },

    updateNodeAttributes(uri: string, nodeName: string, attrs: Record<string, unknown> | null): void {
      this.updateNodeField(uri, nodeName, 'attributes', attrs);
    },

    updateNodeKeys(uri: string, nodeName: string, kind: 'pull_keys' | 'push_keys', keys: Record<string, string> | null | undefined): void {
      this.updateNodeField(uri, nodeName, kind, keys);
    },

    updateEdgeKeys(uri: string, edgeIndex: number, keys: Record<string, string> | null | undefined): void {
      this.updateEdge(uri, edgeIndex, { keys });
    },

    updateEdgeField(uri: string, edgeIndex: number, field: string, value: unknown): void {
      if (!uri || !field) return;
      if (field !== 'from' && field !== 'to' && field !== 'keys') return;
      this.updateEdge(uri, edgeIndex, { [field]: value });
    },

    removeDanglingLayout(uri: string): void {
      const graph = this.activeGraph;
      if (!uri || !graph) return;
      const nodes = Array.isArray(graph.Nodes) ? graph.Nodes : [];
      const valid = new Set<string>(['entry', 'exit']);
      for (const n of nodes) {
        if (!n || typeof n !== 'object') continue;
        const name = String((n as any).name || '');
        if (!name) continue;
        valid.add(name);
        valid.add(`${name}.entry`);
        valid.add(`${name}.exit`);
        valid.add(`${name}.controller`);
        valid.add(`${name}.terminate`);
      }
      const cur = this.layouts[uri] || {};
      const next: VibeLayout = {};
      for (const [k, v] of Object.entries(cur)) {
        if (!valid.has(k)) continue;
        next[k] = v;
      }
      this.layouts = { ...this.layouts, [uri]: next };
    },

    // Validate whether an edge between two nodes is allowed in the current graph scope.
    isEdgeAllowed(uri: string, from: string, to: string): boolean {
      if (!uri || !from || !to) return false;
      if (from === to) return false;
      if (isInternalNodeId(from) || isInternalNodeId(to)) return false;
      const doc = this.docs[uri];
      const graph = doc?.dirtyGraph || doc?.graph;
      if (!graph) return false;
      const nodes = Array.isArray(graph.Nodes) ? graph.Nodes : [];
      const parentByName: Record<string, string | undefined> = {};
      for (const n of nodes) {
        const name = String((n as any)?.name || '');
        if (!name) continue;
        const parent = typeof (n as any)?.parent === 'string' && (n as any).parent.trim() ? (n as any).parent.trim() : undefined;
        parentByName[name] = parent;
      }
      const fromParent = parentOfEndpoint(from, parentByName);
      const toParent = parentOfEndpoint(to, parentByName);
      return fromParent === toParent;
    }
  }
});
