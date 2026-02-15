<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import cytoscape, { type Core, type ElementDefinition } from 'cytoscape';
import type { VibeGraphDesign, VibeLayout, VibeLayoutMeta } from '../stores/vibe';
import { ensureCyDagreRegistered } from '../utils/cyDagre';
import { applySmartDagreLayout, safeFit } from '../utils/cyLayoutPipeline';
import {
  captureSelectionSnapshot,
  captureViewportSnapshot,
  restoreSelectionSnapshot,
  restoreViewportSnapshot
} from '../utils/cyViewport';
import { graphStructureSignature, maybeAutoLayout as maybeAutoLayoutGate } from '../utils/vibeAutoLayout';
import { isCyLayoutDegenerate, uniqueNodePositionCount } from '../utils/cyLayoutFallback';
import { buildVibeElements } from '../utils/vibeElements';

ensureCyDagreRegistered();

const props = defineProps<{
  docUri?: string;
  graph: VibeGraphDesign;
  layout?: VibeLayout;
  layoutMeta?: VibeLayoutMeta | null;
  invalidNodes?: readonly string[];
  invalidEdges?: readonly number[];
}>();

const emit = defineEmits<{
  (e: 'selectNode', nodeId: string): void;
  (e: 'selectEdge', edgeIndex: number): void;
  (e: 'clearSelection'): void;
  (e: 'nodePosition', nodeId: string, pos: { x: number; y: number }): void;
  (e: 'layoutSnapshot', payload: { docUri: string; sig: string; reason: 'auto' | 'force' | 'recovery'; layout: VibeLayout }): void;
  (e: 'nodeParentChanged', payload: { nodeId: string; parent?: string }): void;
  (e: 'dropComponent', payload: { componentType: string; x: number; y: number; parent?: string }): void;
  (e: 'createEdge', payload: { from: string; to: string }): void;
}>();

const rootRef = ref<HTMLDivElement | null>(null);
const containerRef = ref<HTMLDivElement | null>(null);
let cy: Core | null = null;
let resizeObserver: ResizeObserver | null = null;
let pendingResizeRaf: number | null = null;
let dragRaf: number | null = null;
const renderError = ref<string | null>(null);
const cyStatus = ref<string>('');
let stabilizeTimer: number | null = null;
let stabilizeAttempts = 0;
let lastContainerSize: { w: number; h: number } = { w: 0, h: 0 };
let lastVisibleViewport:
  | { docUri: string; viewport: { zoom: number; pan: { x: number; y: number } } }
  | null = null;

type EdgeModeKind = 'from' | 'to';

const edgeModeActive = ref(false);
const edgeModeKind = ref<EdgeModeKind>('from');
const edgeModeAnchorId = ref('');
const edgeModeScopeParent = ref('');

const edgeModeTitle = computed(() => (edgeModeKind.value === 'from' ? 'From' : 'To'));
const edgeModeSubtitle = computed(() =>
  edgeModeKind.value === 'from' ? 'Click a target node to connect' : 'Click a source node to connect'
);

const contextMenu = ref<{ visible: boolean; x: number; y: number; nodeId: string | null }>({
  visible: false,
  x: 0,
  y: 0,
  nodeId: null
});

const dragTarget = ref<string | null>(null);
const dragHint = ref<string>('');

let lastGhostModelPos: { x: number; y: number } | null = null;
let ghostRaf: number | null = null;
let dragScopeBoxes: Array<{ id: string; bb: { x1: number; x2: number; y1: number; y2: number }; area: number }> | null =
  null;
let grabbedNodeId: string | null = null;
let grabbedStartPos: { x: number; y: number } | null = null;
let compoundDrag:
  | {
      parentId: string;
      startParentPos: { x: number; y: number };
      startPosById: Map<string, { x: number; y: number }>;
    }
  | null = null;
let edgeModeKeydown: ((e: KeyboardEvent) => void) | null = null;
let prevAutoungrabify: boolean | null = null;
let prevAutounselectify: boolean | null = null;

const GHOST_NODE_ID = '__vibe_ghost__';
const GHOST_EDGE_ID = '__vibe_ghost_edge__';

let lastAutoLayoutSig: string | null = null;
let lastDocUri: string | null = null;
let lastRenderedGraphSig: string | null = null;
let lastRenderedLayoutSig: string | null = null;
let lastRenderedInvalidSig: string | null = null;

function parseEndpoint(name: string): { base: string; suffix: string | null } {
  const s = String(name || '');
  const idx = s.indexOf('.');
  if (idx === -1) return { base: s, suffix: null };
  return { base: s.slice(0, idx), suffix: s.slice(idx + 1) || null };
}

function handleSupport(id: string, type: string): { inOk: boolean; outOk: boolean } {
  const isEntry = type === 'entry' || id === 'entry' || id.endsWith('.entry');
  const isExit = type === 'exit' || id === 'exit' || id.endsWith('.exit');
  const isTerminate = type === 'TerminateNode' || id.endsWith('.terminate');
  if (isEntry) return { inOk: false, outOk: true };
  if (isExit || isTerminate) return { inOk: true, outOk: false };
  return { inOk: true, outOk: true };
}

function updateCyStatus(): void {
  if (!cy) {
    cyStatus.value = '';
    return;
  }
  const nodeCount = cy.nodes().length;
  const edgeCount = cy.edges().length;
  let unique = 0;
  try {
    unique = uniqueNodePositionCount(cy, { leafOnly: false });
  } catch {
    unique = 0;
  }
  let zoom = 0;
  let panX = 0;
  let panY = 0;
  try {
    zoom = cy.zoom();
    const pan = cy.pan();
    panX = typeof pan?.x === 'number' && Number.isFinite(pan.x) ? pan.x : 0;
    panY = typeof pan?.y === 'number' && Number.isFinite(pan.y) ? pan.y : 0;
  } catch {
    // ignore
  }
  const w = containerRef.value?.clientWidth ?? 0;
  const h = containerRef.value?.clientHeight ?? 0;

  let bbText = '';
  try {
    const bb = cy.elements().boundingBox();
    const bw = typeof bb?.w === 'number' && Number.isFinite(bb.w) ? Math.round(bb.w) : 0;
    const bh = typeof bb?.h === 'number' && Number.isFinite(bb.h) ? Math.round(bb.h) : 0;
    bbText = `${bw}x${bh}`;
  } catch {
    bbText = '';
  }

  let visibleNodes = 0;
  try {
    visibleNodes = cy.nodes().filter((n) => n && typeof n.visible === 'function' && n.visible()).length;
  } catch {
    visibleNodes = 0;
  }

  let sampleIds = '';
  try {
    const nodes = cy.nodes().toArray();
    const limit = Math.min(4, nodes.length);
    const ids: string[] = [];
    for (let i = 0; i < limit; i++) {
      const n = nodes[i];
      const id = typeof n?.id === 'function' ? n.id() : '';
      if (id) ids.push(id);
    }
    sampleIds = ids.join(', ');
  } catch {
    sampleIds = '';
  }

  const extras = [
    bbText ? `bb:${bbText}` : '',
    `vis:${visibleNodes}`,
    sampleIds ? `ids:${sampleIds}` : ''
  ]
    .filter(Boolean)
    .join(' · ');
  cyStatus.value = `cy: ${nodeCount}n·${edgeCount}e · pos:${unique} · zoom:${zoom.toFixed(
    3
  )} · pan:${panX.toFixed(0)},${panY.toFixed(0)} · size:${w}x${h}${extras ? ` · ${extras}` : ''}`;
}

function isContainerVisible(): boolean {
  const w = containerRef.value?.clientWidth ?? 0;
  const h = containerRef.value?.clientHeight ?? 0;
  return w >= 20 && h >= 20;
}

function scheduleStabilize(reason: string): void {
  if (!cy) return;
  if (stabilizeTimer !== null) {
    try {
      clearTimeout(stabilizeTimer);
    } catch {
      // ignore
    }
    stabilizeTimer = null;
  }

  stabilizeAttempts = 0;

  const tick = () => {
    stabilizeTimer = null;
    if (!cy) return;
    stabilizeAttempts += 1;

    const w = containerRef.value?.clientWidth ?? 0;
    const h = containerRef.value?.clientHeight ?? 0;
    if (w < 20 || h < 20) {
      if (stabilizeAttempts < 10) {
        stabilizeTimer = window.setTimeout(tick, 120);
      }
      return;
    }

    // Cytoscape can initialize while hidden (tab switch) and compute a bad viewport.
    // Once we know the container has a real size, stabilize the view once.
    try {
      const layout = props.layout;
      const layoutEmpty =
        !layout || (typeof layout === 'object' && Object.keys(layout as Record<string, unknown>).length === 0);

      try {
        cy.resize();
      } catch {
        // ignore
      }

      const activeDocUri = typeof props.docUri === 'string' ? props.docUri : '';
      const snap =
        reason === 'resize-from-hidden' && lastVisibleViewport?.docUri === activeDocUri
          ? lastVisibleViewport.viewport
          : null;
      if (snap) {
        restoreViewportSnapshot(cy, snap);
        try {
          if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(() => {
              if (!cy) return;
              restoreViewportSnapshot(cy, snap);
            });
          }
        } catch {
          // ignore
        }
      } else if (reason !== 'resize-from-hidden' && layoutEmpty && isCyLayoutDegenerate(cy)) {
        // Only attempt a recovery relayout when initializing/changing documents.
        relayoutAndFit('force');
      } else {
        safeFit(cy, 30);
      }
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn('[MASFactory Visualizer][VibeGraphEditor] stabilize failed:', reason, err);
    }
    updateCyStatus();
  };

  stabilizeTimer = window.setTimeout(tick, 80);
}

function captureLayoutSnapshot(core: Core): VibeLayout {
  const out: VibeLayout = {};
  try {
    core.nodes().forEach((n) => {
      if (!n || !n.isNode || !n.isNode()) return;
      const id = typeof n.id === 'function' ? n.id() : '';
      if (!id) return;
      if (id.startsWith('__vibe_ghost__')) return;
      // Skip compound parents: their position is derived from children and setting it can translate descendants.
      if (n.isParent && n.isParent()) return;
      const p = n.position();
      const x = typeof p?.x === 'number' && Number.isFinite(p.x) ? p.x : null;
      const y = typeof p?.y === 'number' && Number.isFinite(p.y) ? p.y : null;
      if (x === null || y === null) return;
      out[id] = { x, y };
    });
  } catch {
    // ignore
  }
  return out;
}

function emitLayoutSnapshot(sig: string, reason: 'auto' | 'force' | 'recovery'): void {
  if (!cy) return;
  const docUri = typeof props.docUri === 'string' ? props.docUri : '';
  const layout = captureLayoutSnapshot(cy);
  emit('layoutSnapshot', { docUri, sig, reason, layout });
}

function maybeAutoLayout(core: Core, graph: VibeGraphDesign, layout?: VibeLayout): void {
  if (!isContainerVisible()) return;
  const layoutEmpty = !layout || (typeof layout === 'object' && Object.keys(layout).length === 0);

  const applyLayout = () => {
    applySmartDagreLayout(core, { preferDirection: 'AUTO', fitPadding: 30, dagreRankDir: 'TB', dagreNodeSep: 40, dagreRankSep: 65 });
  };

  const result = maybeAutoLayoutGate(
    { previousSig: lastAutoLayoutSig, graph, layout, layoutMeta: props.layoutMeta || null },
    applyLayout
  );

  // If auto-layout was gated off (e.g. same signature) but the current view is
  // clearly broken (all nodes stacked) and we have no persisted layout, force
  // a one-time recovery layout.
  let didRecovery = false;
  if (!result.applied && layoutEmpty && isCyLayoutDegenerate(core)) {
    applyLayout();
    didRecovery = true;
  }
  if (result.applied) {
    emitLayoutSnapshot(result.nextSig, 'auto');
  } else if (didRecovery) {
    emitLayoutSnapshot(result.nextSig, 'recovery');
  }
  lastAutoLayoutSig = result.nextSig;
}

function closeContextMenu(): void {
  contextMenu.value = { visible: false, x: 0, y: 0, nodeId: null };
}

function openContextMenu(nodeId: string, e: MouseEvent): void {
  if (!rootRef.value) return;
  const rect = rootRef.value.getBoundingClientRect();
  const rawX = e.clientX - rect.left;
  const rawY = e.clientY - rect.top;
  const x = Math.max(8, Math.min(rect.width - 8, rawX));
  const y = Math.max(8, Math.min(rect.height - 8, rawY));
  contextMenu.value = { visible: true, x, y, nodeId };
}

function setDragTarget(targetId: string | null): void {
  if (!cy) return;
  const prev = dragTarget.value;
  if (prev && !cy.getElementById(prev).empty()) {
    cy.getElementById(prev).removeClass('drop-target');
  }
  dragTarget.value = targetId;
  if (targetId && !cy.getElementById(targetId).empty()) {
    cy.getElementById(targetId).addClass('drop-target');
  }
}

function scheduleDragUpdate(): void {
  if (dragRaf !== null) return;
  dragRaf = requestAnimationFrame(() => {
    dragRaf = null;
    updateDragHover();
  });
}

function updateDragHover(): void {
  if (!cy) return;
  if (!grabbedNodeId) return;
  if (edgeModeActive.value) return;
  const node = cy.getElementById(grabbedNodeId);
  if (!node || node.empty()) return;
  const pos = node.position();
  const currentParent = String(node.data('parent') || '');
  const nextParent = computeNextParent(grabbedNodeId, { x: pos.x, y: pos.y });
  const normalizedCurrent = currentParent ? currentParent : undefined;
  const normalizedNext = nextParent ? nextParent : undefined;
  if (normalizedNext && normalizedNext !== normalizedCurrent) {
    setDragTarget(normalizedNext);
    dragHint.value = `Release to move into ${normalizedNext}. Existing edges will be removed.`;
  } else {
    setDragTarget(null);
    dragHint.value = '';
  }
}

function beginCompoundDrag(parentNode: any): void {
  if (!cy) return;
  const id = String(parentNode?.id?.() || '');
  if (!id) return;
  const startParentPos = parentNode.position?.();
  if (!startParentPos) return;
  const startPosById = new Map<string, { x: number; y: number }>();
  try {
    const descendants = parentNode.descendants?.();
    descendants?.forEach?.((d: any) => {
      const did = String(d?.id?.() || '');
      if (!did) return;
      const p = d.position?.();
      if (!p) return;
      startPosById.set(did, { x: p.x, y: p.y });
    });
  } catch {
    // ignore
  }
  compoundDrag = {
    parentId: id,
    startParentPos: { x: startParentPos.x, y: startParentPos.y },
    startPosById
  };
}

function applyCompoundDrag(parentNode: any): void {
  if (!cy || !compoundDrag) return;
  const id = String(parentNode?.id?.() || '');
  if (!id || id !== compoundDrag.parentId) return;
  const p = parentNode.position?.();
  if (!p) return;
  const dx = p.x - compoundDrag.startParentPos.x;
  const dy = p.y - compoundDrag.startParentPos.y;
  if (dx === 0 && dy === 0) return;
  cy.batch(() => {
    for (const [did, sp] of compoundDrag!.startPosById.entries()) {
      const el = cy!.getElementById(did);
      if (!el || el.empty()) continue;
      try {
        el.position({ x: sp.x + dx, y: sp.y + dy });
      } catch {
        // ignore
      }
    }
  });
}

function resetDragState(): void {
  grabbedNodeId = null;
  grabbedStartPos = null;
  dragScopeBoxes = null;
  compoundDrag = null;
  setDragTarget(null);
  dragHint.value = '';
}

function applyEdgeModeClasses(scopeParent: string, anchorId: string, kind: EdgeModeKind): void {
  if (!cy) return;
  const parentKey = String(scopeParent || '');
  const want: 'in' | 'out' = kind === 'from' ? 'in' : 'out';
  cy.nodes().forEach((n) => {
    const id = n.id();
    const sameLevel = String(n.data('parent') || '') === parentKey;
    if (!sameLevel) {
      n.addClass('vibe-dim');
      n.removeClass('vibe-target');
      return;
    }
    n.removeClass('vibe-dim');
    if (id === anchorId) {
      n.removeClass('vibe-target');
      return;
    }
    const type = String(n.data('type') || 'Node');
    const sup = handleSupport(id, type);
    const ok = want === 'in' ? sup.inOk : sup.outOk;
    if (ok) n.addClass('vibe-target');
    else n.removeClass('vibe-target');
  });
  cy.edges().addClass('vibe-dim-edge');
}

function ensureGhost(kind: EdgeModeKind, anchorId: string, modelPos: { x: number; y: number }): void {
  if (!cy) return;
  const ghostNodeExists = !cy.getElementById(GHOST_NODE_ID).empty();
  if (!ghostNodeExists) {
    cy.add({
      group: 'nodes',
      data: { id: GHOST_NODE_ID, label: '', type: 'Ghost', internal: '1' },
      position: { x: modelPos.x, y: modelPos.y },
      grabbable: false,
      selectable: false,
      locked: true
    });
  }
  const ghostEdgeExists = !cy.getElementById(GHOST_EDGE_ID).empty();
  if (!ghostEdgeExists) {
    cy.add({
      group: 'edges',
      data: {
        id: GHOST_EDGE_ID,
        source: kind === 'from' ? anchorId : GHOST_NODE_ID,
        target: kind === 'from' ? GHOST_NODE_ID : anchorId,
        label: ''
      },
      selectable: false
    });
  } else {
    const edge = cy.getElementById(GHOST_EDGE_ID);
    edge.data('source', kind === 'from' ? anchorId : GHOST_NODE_ID);
    edge.data('target', kind === 'from' ? GHOST_NODE_ID : anchorId);
  }
  cy.getElementById(GHOST_NODE_ID).position({ x: modelPos.x, y: modelPos.y });
  lastGhostModelPos = { x: modelPos.x, y: modelPos.y };
}

function clearEdgeMode(): void {
  edgeModeActive.value = false;
  edgeModeAnchorId.value = '';
  edgeModeScopeParent.value = '';
  lastGhostModelPos = null;
  if (!cy) return;
  try {
    cy.getElementById(GHOST_EDGE_ID).remove();
  } catch {
    // ignore
  }
  try {
    cy.getElementById(GHOST_NODE_ID).remove();
  } catch {
    // ignore
  }
  cy.nodes().removeClass('vibe-dim vibe-target');
  cy.edges().removeClass('vibe-dim-edge');
  if (prevAutoungrabify !== null) {
    try {
      cy.autoungrabify(prevAutoungrabify);
    } catch {
      // ignore
    }
  }
  if (prevAutounselectify !== null) {
    try {
      cy.autounselectify(prevAutounselectify);
    } catch {
      // ignore
    }
  }
  prevAutoungrabify = null;
  prevAutounselectify = null;
}

function cancelEdgeMode(): void {
  clearEdgeMode();
}

function startEdgeMode(kind: EdgeModeKind, anchorId: string): void {
  if (!cy) return;
  const node = cy.getElementById(anchorId);
  if (!node || node.empty()) return;
  const type = String(node.data('type') || 'Node');
  const sup = handleSupport(anchorId, type);
  if (kind === 'from' && !sup.outOk) return;
  if (kind === 'to' && !sup.inOk) return;

  edgeModeActive.value = true;
  edgeModeKind.value = kind;
  edgeModeAnchorId.value = anchorId;
  edgeModeScopeParent.value = String(node.data('parent') || '');

  applyEdgeModeClasses(edgeModeScopeParent.value, anchorId, kind);

  try {
    prevAutoungrabify = cy.autoungrabify();
    prevAutounselectify = cy.autounselectify();
    cy.autoungrabify(true);
    cy.autounselectify(true);
  } catch {
    // ignore
  }

  const p = node.position();
  ensureGhost(kind, anchorId, { x: p.x, y: p.y });
}

function completeEdge(candidateId: string): void {
  if (!edgeModeActive.value) return;
  const anchor = edgeModeAnchorId.value;
  if (!anchor) return;
  const from = edgeModeKind.value === 'from' ? anchor : candidateId;
  const to = edgeModeKind.value === 'from' ? candidateId : anchor;
  clearEdgeMode();
  emit('createEdge', { from, to });
}

function renderedToModel(clientX: number, clientY: number): { x: number; y: number } {
  if (!cy || !containerRef.value) return { x: 0, y: 0 };
  const rect = containerRef.value.getBoundingClientRect();
  const renderedX = clientX - rect.left;
  const renderedY = clientY - rect.top;
  const zoom = cy.zoom();
  const pan = cy.pan();
  return { x: (renderedX - pan.x) / zoom, y: (renderedY - pan.y) / zoom };
}

function onMouseMove(e: MouseEvent): void {
  if (!edgeModeActive.value || !cy) return;
  lastGhostModelPos = renderedToModel(e.clientX, e.clientY);
  if (ghostRaf !== null) return;
  ghostRaf = requestAnimationFrame(() => {
    ghostRaf = null;
    if (!cy || !edgeModeActive.value || !lastGhostModelPos) return;
    try {
      const ghost = cy.getElementById(GHOST_NODE_ID);
      if (!ghost.empty()) ghost.position({ x: lastGhostModelPos.x, y: lastGhostModelPos.y });
    } catch {
      // ignore
    }
  });
}

function relayoutAndFit(kind: 'auto' | 'force' = 'force'): void {
  if (!cy) return;
  if (!isContainerVisible()) return;
  const graph = props.graph;
  if (!graph) return;
  renderError.value = null;
  try {
    if (kind === 'auto') {
      maybeAutoLayout(cy, graph, props.layout);
      updateCyStatus();
      return;
    }
    applySmartDagreLayout(cy, { preferDirection: 'AUTO', fitPadding: 30, dagreRankDir: 'TB', dagreNodeSep: 40, dagreRankSep: 65 });
    try {
      const sig = graphStructureSignature(graph);
      emitLayoutSnapshot(sig, 'force');
    } catch {
      // ignore
    }
    updateCyStatus();
  } catch (err) {
    const msg = err instanceof Error ? err.stack || err.message : String(err);
    renderError.value = msg;
    // eslint-disable-next-line no-console
    console.error('[MASFactory Visualizer][VibeGraphEditor] relayout failed:', err);
    updateCyStatus();
  }
}

function fitView(): void {
  if (!cy) return;
  renderError.value = null;
  safeFit(cy, 30);
  updateCyStatus();
}

function invalidSignature(): string {
  const nodes = Array.isArray(props.invalidNodes) ? props.invalidNodes : [];
  const edges = Array.isArray(props.invalidEdges) ? props.invalidEdges : [];
  try {
    const ns = nodes.map((n) => String(n)).sort().join(',');
    const es = edges.map((n) => String(n)).sort().join(',');
    return `${ns}||${es}`;
  } catch {
    return '';
  }
}

function applyInvalidMarkers(): void {
  if (!cy) return;
  const invalidNodeSet = new Set<string>(Array.isArray(props.invalidNodes) ? props.invalidNodes.map(String) : []);
  const invalidEdgeSet = new Set<string>(
    Array.isArray(props.invalidEdges) ? props.invalidEdges.map((n) => `edge:${Number(n)}`) : []
  );

  try {
    cy.nodes().forEach((n) => {
      if (!n || !n.isNode || !n.isNode()) return;
      const id = n.id();
      if (invalidNodeSet.has(id)) n.addClass('invalid');
      else n.removeClass('invalid');
    });
  } catch {
    // ignore
  }

  try {
    cy.edges().forEach((e) => {
      if (!e || !e.isEdge || !e.isEdge()) return;
      const id = e.id();
      if (invalidEdgeSet.has(id)) e.addClass('invalid-edge');
      else e.removeClass('invalid-edge');
    });
  } catch {
    // ignore
  }
}

function applyLayoutPositions(layout?: VibeLayout): void {
  if (!cy || !layout || typeof layout !== 'object') return;
  const ids: string[] = [];
  try {
    for (const nodeId of Object.keys(layout)) {
      const n = cy.getElementById(nodeId);
      if (!n || n.empty() || !n.isNode()) continue;
      if (n.isParent && n.isParent()) continue;
      ids.push(nodeId);
    }
  } catch {
    // ignore
  }

  cy.batch(() => {
    for (const nodeId of ids) {
      const p = (layout as any)[nodeId];
      const x = typeof p?.x === 'number' && Number.isFinite(p.x) ? p.x : null;
      const y = typeof p?.y === 'number' && Number.isFinite(p.y) ? p.y : null;
      if (x === null || y === null) continue;
      const n = cy!.getElementById(nodeId);
      if (!n || n.empty() || !n.isNode()) continue;
      try {
        n.position({ x, y });
      } catch {
        // ignore
      }
    }
  });
}

function render(): void {
  if (!containerRef.value) return;
  const graph = props.graph;
  if (!graph) return;
  renderError.value = null;

  const docUri = typeof props.docUri === 'string' ? props.docUri : null;
  const docChanged = !!docUri && docUri !== lastDocUri;
  if (docChanged) {
    lastDocUri = docUri;
    lastAutoLayoutSig = null;
    clearEdgeMode();
    closeContextMenu();
    setDragTarget(null);
  }

  const nextGraphSig = graphSig.value;
  const nextLayoutSig = layoutSig.value;
  const nextInvalidSig = invalidSignature();

  const graphChanged = docChanged || lastRenderedGraphSig === null || nextGraphSig !== lastRenderedGraphSig;
  const layoutChanged = lastRenderedLayoutSig === null || nextLayoutSig !== lastRenderedLayoutSig;
  const invalidChanged = lastRenderedInvalidSig === null || nextInvalidSig !== lastRenderedInvalidSig;

  // Fast path: only positions/invalid markers changed; don't replace all elements.
  if (cy && !graphChanged) {
    if (layoutChanged) {
      applyLayoutPositions(props.layout);
    }
    if (invalidChanged) {
      applyInvalidMarkers();
    }
    if (layoutChanged || invalidChanged) {
      updateCyStatus();
      lastRenderedGraphSig = nextGraphSig;
      lastRenderedLayoutSig = nextLayoutSig;
      lastRenderedInvalidSig = nextInvalidSig;
      return;
    }
  }

  let elements: ElementDefinition[] = [];
  try {
    const existingPositions: Record<string, { x: number; y: number }> = {};
    if (cy) {
      cy.nodes().forEach((n) => {
        existingPositions[n.id()] = n.position();
      });
    }
    const mergedPositions = { ...existingPositions, ...(props.layout || {}) };
    const invalidNodes = new Set<string>(Array.isArray(props.invalidNodes) ? props.invalidNodes : []);
    const invalidEdges = new Set<number>(
      Array.isArray(props.invalidEdges) ? props.invalidEdges.map((n) => Number(n)).filter(Number.isFinite) : []
    );
    elements = buildVibeElements(graph, mergedPositions, invalidNodes, invalidEdges);
  } catch (err) {
    const msg = err instanceof Error ? err.stack || err.message : String(err);
    renderError.value = msg;
    // eslint-disable-next-line no-console
    console.error('[MASFactory Visualizer][VibeGraphEditor] buildElements failed:', err);
    return;
  }

  if (!cy) {
    cy = cytoscape({
      container: containerRef.value,
      elements,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'text-valign': 'center',
            'text-halign': 'center',
            'font-size': 11,
            color: '#d4d4d4',
            'background-color': '#2d2d2d',
            'border-width': 2,
            'border-color': '#5a5a5a',
            width: 'data(w)',
            height: 'data(h)',
            'text-wrap': 'wrap',
            'text-max-width': '240px',
            shape: 'round-rectangle'
          }
        },
        {
          selector: `#${GHOST_NODE_ID}`,
          style: {
            label: '',
            width: 1,
            height: 1,
            opacity: 0,
            'background-opacity': 0,
            'border-opacity': 0,
            events: 'no'
          }
        },
        {
          selector: `#${GHOST_EDGE_ID}`,
          style: {
            'line-style': 'dashed',
            'line-color': '#f2cc60',
            'target-arrow-color': '#f2cc60',
            width: 2,
            opacity: 0.85
          }
        },
        {
          selector: 'node[type="entry"], node[type="exit"], node[id="entry"], node[id="exit"]',
          style: {
            shape: 'ellipse',
            'background-color': '#1e5631',
            'border-color': '#2d8659'
          }
        },
        {
          selector: 'node[type="Controller"]',
          style: {
            shape: 'ellipse',
            'background-color': '#1e4a5c',
            'border-color': '#2d7a9c',
            width: '70px',
            height: '35px',
            'font-size': 11,
            padding: '5px'
          }
        },
        {
          selector: 'node.subgraph',
          style: {
            label: '',
            'background-color': 'rgba(50, 50, 50, 0.22)',
            'border-style': 'dashed',
            'border-width': 2,
            'border-color': '#5a5a5a',
            'min-width': 240,
            'min-height': 180,
            'padding-top': 14,
            'padding-left': 14,
            'padding-right': 14,
            'padding-bottom': 14
          }
        },
        {
          selector: 'node.subgraph.drop-target',
          style: {
            'border-style': 'solid',
            'border-width': 3,
            'border-color': '#f2cc60'
          }
        },
        {
          selector: 'edge',
          style: {
            width: 2,
            'line-color': '#cccccc',
            'target-arrow-color': '#cccccc',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': 9,
            color: '#8fb9d1',
            'text-rotation': 'none',
            'edge-text-rotation': 'none',
            'text-wrap': 'wrap',
            'text-max-width': '120px'
          }
        },
        {
          selector: 'node:selected',
          style: {
            'border-color': '#4fc3f7',
            'border-width': 3
          }
        },
        {
          selector: 'edge:selected',
          style: {
            'line-color': '#4fc3f7',
            'target-arrow-color': '#4fc3f7',
            width: 3
          }
        },
        {
          selector: 'node.invalid',
          style: {
            'border-color': '#f2cc60',
            'border-width': 3
          }
        },
        {
          selector: 'edge.invalid-edge',
          style: {
            'line-color': '#f2cc60',
            'target-arrow-color': '#f2cc60',
            'line-style': 'dashed',
            width: 3
          }
        },
        {
          selector: '.vibe-dim',
          style: {
            opacity: 0.7,
            events: 'no'
          }
        },
        {
          selector: '.vibe-dim-edge',
          style: {
            opacity: 0.7,
            events: 'no'
          }
        },
        {
          selector: 'node.vibe-target',
          style: {
            'border-color': '#f2cc60',
            'border-width': 3
          }
        },
        {
          selector: 'node[internal="1"]',
          style: {
            'background-opacity': 1
          }
        }
      ],
      layout: { name: 'preset' },
      wheelSensitivity: 1.2
    });

    cy.on('tap', (evt) => {
      closeContextMenu();
      if (edgeModeActive.value) return;
      if (evt.target === cy) emit('clearSelection');
    });

    cy.on('tap', 'node', (evt) => {
      closeContextMenu();
      const node = evt.target;
      const id = node.id();
      if (edgeModeActive.value) {
        if (node.hasClass('vibe-target')) completeEdge(id);
        return;
      }
      emit('selectNode', id);
    });

    cy.on('tap', 'edge', (evt) => {
      closeContextMenu();
      if (edgeModeActive.value) return;
      const edge = evt.target;
      const raw = edge.data('edgeIndex');
      const idx = Number(raw);
      if (Number.isFinite(idx)) emit('selectEdge', idx);
    });

    cy.on('pan zoom', () => {
      if (contextMenu.value.visible) closeContextMenu();
    });

    cy.on('cxttap', (evt) => {
      if (edgeModeActive.value) return;
      if (evt.target === cy) closeContextMenu();
    });

    cy.on('cxttap', 'node', (evt) => {
      if (edgeModeActive.value) return;
      const node = evt.target;
      const id = node.id();
      if (String(node.data('internal') || '') === '1') return;
      emit('selectNode', id);
      const oe = (evt as any).originalEvent as MouseEvent | undefined;
      if (oe) openContextMenu(id, oe);
    });

    cy.on('grab', 'node', (evt) => {
      if (edgeModeActive.value) return;
      closeContextMenu();
      const node = evt.target;
      if (String(node.data('internal') || '') === '1') return;
      resetDragState();
      grabbedNodeId = node.id();
      grabbedStartPos = node.position();
      dragScopeBoxes = snapshotScopeBoxes(node.id());
      try {
        if (node.isParent && node.isParent()) {
          beginCompoundDrag(node);
        }
      } catch {
        // ignore
      }
    });

    cy.on('drag', 'node', (evt) => {
      if (edgeModeActive.value) return;
      const node = evt.target;
      const id = node.id();
      if (!grabbedNodeId || id !== grabbedNodeId) return;
      if (String(node.data('internal') || '') === '1') return;
      if (compoundDrag && compoundDrag.parentId === id) {
        applyCompoundDrag(node);
      }
      scheduleDragUpdate();
    });

    cy.on('dragfree', 'node', (evt) => {
      const node = evt.target;
      const id = node.id();
      if (edgeModeActive.value) return;
      if (String(node.data('internal') || '') === '1') {
        const p = node.position();
        emit('nodePosition', id, { x: p.x, y: p.y });
        return;
      }

      const isPrimary = !!grabbedNodeId && id === grabbedNodeId;
      const curParent = String(node.data('parent') || '');
      const normalizedCurrent = curParent ? curParent : undefined;
      const p0 = node.position();
      const nextParent = isPrimary ? computeNextParent(id, { x: p0.x, y: p0.y }) : undefined;
      const normalizedNext = nextParent ? nextParent : undefined;

      const shouldRevert = isPrimary && !normalizedNext && !!normalizedCurrent && !!grabbedStartPos;
      if (shouldRevert) {
        try {
          node.position({ x: grabbedStartPos!.x, y: grabbedStartPos!.y });
        } catch {
          // ignore
        }
        if (compoundDrag && compoundDrag.parentId === id) {
          try {
            cy.batch(() => {
              for (const [did, sp] of compoundDrag!.startPosById.entries()) {
                const el = cy!.getElementById(did);
                if (!el || el.empty()) continue;
                el.position({ x: sp.x, y: sp.y });
              }
            });
          } catch {
            // ignore
          }
        }
      } else if (isPrimary && normalizedNext && normalizedNext !== normalizedCurrent) {
        emit('nodeParentChanged', { nodeId: id, parent: normalizedNext });
      }

      // Persist final positions (after possible revert/compound adjustment).
      const finalP = node.position();
      const isCompoundParent = !!(node.isParent && node.isParent());
      if (!isCompoundParent) {
        emit('nodePosition', id, { x: finalP.x, y: finalP.y });
      }
      try {
        if (isCompoundParent) {
          const kids = node.descendants ? node.descendants() : null;
          kids?.forEach?.((k: any) => {
            const kidId = String(k.id?.() || '');
            if (!kidId) return;
            const kp = k.position?.();
            if (kp) emit('nodePosition', kidId, { x: kp.x, y: kp.y });
          });
        }
      } catch {
        // ignore
      }

      if (isPrimary) resetDragState();
    });
    edgeModeKeydown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (!edgeModeActive.value) return;
      cancelEdgeMode();
    };
    window.addEventListener('keydown', edgeModeKeydown);

    // Auto layout when the current document has no persisted layout.
    relayoutAndFit('auto');
    if (docChanged) safeFit(cy, 30);
    applyInvalidMarkers();
    updateCyStatus();
    scheduleStabilize('init');

    // Resize observer for container.
    try {
      resizeObserver = new ResizeObserver(() => {
        if (!cy) return;
        if (pendingResizeRaf !== null) cancelAnimationFrame(pendingResizeRaf);
        pendingResizeRaf = requestAnimationFrame(() => {
          pendingResizeRaf = null;
          const w = containerRef.value?.clientWidth ?? 0;
          const h = containerRef.value?.clientHeight ?? 0;
          const prev = lastContainerSize;
          lastContainerSize = { w, h };
          const wasVisible = prev.w >= 20 && prev.h >= 20;
          const isVisible = w >= 20 && h >= 20;
          if (wasVisible && !isVisible) {
            const viewport = captureViewportSnapshot(cy);
            const docUri = typeof props.docUri === 'string' ? props.docUri : '';
            lastVisibleViewport = viewport ? { docUri, viewport } : null;
          }
          cy?.resize();
          updateCyStatus();
          if (!wasVisible && isVisible) {
            const docUri = typeof props.docUri === 'string' ? props.docUri : '';
            const snap = lastVisibleViewport?.docUri === docUri ? lastVisibleViewport.viewport : null;
            if (snap) {
              restoreViewportSnapshot(cy, snap);
              try {
                if (typeof requestAnimationFrame === 'function') {
                  requestAnimationFrame(() => {
                    if (!cy) return;
                    cy.resize();
                    restoreViewportSnapshot(cy, snap);
                    updateCyStatus();
                  });
                }
              } catch {
                // ignore
              }
            } else {
              scheduleStabilize('resize-from-hidden');
            }
            // If we became visible and there is no persisted layout yet, run the initial auto-layout once.
            try {
              const layout = props.layout;
              const layoutEmpty =
                !layout || (typeof layout === 'object' && Object.keys(layout as Record<string, unknown>).length === 0);
              if (layoutEmpty) relayoutAndFit('auto');
            } catch {
              // ignore
            }
          }
        });
      });
      resizeObserver.observe(containerRef.value);
    } catch {
      // ignore
    }
  } else {
    try {
      const prevViewport = captureViewportSnapshot(cy);
      const prevSelection = captureSelectionSnapshot(cy);

      cy.elements().remove();
      cy.add(elements);
      cy.layout({ name: 'preset' }).run();

      // Rebuilds reset viewport/selection in Cytoscape; restore so graph editing doesn't "jump".
      restoreViewportSnapshot(cy, prevViewport);
      restoreSelectionSnapshot(cy, prevSelection);

      // When switching documents, the cytoscape instance persists. Ensure we
      // still auto-layout the new graph if it has no persisted layout yet.
      if (docChanged || graphChanged) relayoutAndFit('auto');
      if (docChanged) safeFit(cy, 30);
      setDragTarget(null);
      applyInvalidMarkers();
      updateCyStatus();
      if (docChanged) scheduleStabilize('doc-change');
    } catch (err) {
      const msg = err instanceof Error ? err.stack || err.message : String(err);
      renderError.value = msg;
      // eslint-disable-next-line no-console
      console.error('[MASFactory Visualizer][VibeGraphEditor] render update failed:', err);
      updateCyStatus();
    }
  }

  lastRenderedGraphSig = nextGraphSig;
  lastRenderedLayoutSig = nextLayoutSig;
  lastRenderedInvalidSig = nextInvalidSig;
}

function snapshotScopeBoxes(draggedId: string): Array<{ id: string; bb: { x1: number; x2: number; y1: number; y2: number }; area: number }> {
  if (!cy) return [];
  const boxes: Array<{ id: string; bb: { x1: number; x2: number; y1: number; y2: number }; area: number }> = [];

  const isDescendant = (id: string, maybeAncestor: string): boolean => {
    if (!cy) return false;
    let cur = cy.getElementById(id);
    while (cur && !cur.empty()) {
      const p = cur.data('parent');
      if (!p) return false;
      if (String(p) === maybeAncestor) return true;
      cur = cy.getElementById(String(p));
    }
    return false;
  };

  cy.nodes('.subgraph').forEach((n) => {
    const id = n.id();
    if (id === draggedId) return;
    if (isDescendant(id, draggedId)) return;
    const bb = n.boundingBox();
    const area = (bb.x2 - bb.x1) * (bb.y2 - bb.y1);
    boxes.push({ id, bb: { x1: bb.x1, x2: bb.x2, y1: bb.y1, y2: bb.y2 }, area });
  });
  boxes.sort((a, b) => a.area - b.area);
  return boxes;
}

function computeNextParent(nodeId: string, pos: { x: number; y: number }): string | undefined {
  if (!cy) return undefined;
  const margin = 24;
  const boxes = dragScopeBoxes || [];
  let chosen: string | undefined;
  for (const b of boxes) {
    if (
      pos.x >= b.bb.x1 - margin &&
      pos.x <= b.bb.x2 + margin &&
      pos.y >= b.bb.y1 - margin &&
      pos.y <= b.bb.y2 + margin
    ) {
      chosen = b.id;
      break;
    }
  }
  return chosen;
}

function onDragOver(e: DragEvent) {
  e.preventDefault();
  closeContextMenu();
}

function onDrop(e: DragEvent) {
  e.preventDefault();
  if (!cy || !containerRef.value) return;
  if (edgeModeActive.value) return;
  closeContextMenu();
  const raw = e.dataTransfer?.getData('application/x-masfactory-visualizer-vibe-component') || '';
  if (!raw) return;
  const componentType = raw;

  const rect = containerRef.value.getBoundingClientRect();
  const renderedX = e.clientX - rect.left;
  const renderedY = e.clientY - rect.top;
  const zoom = cy.zoom();
  const pan = cy.pan();
  const x = (renderedX - pan.x) / zoom;
  const y = (renderedY - pan.y) / zoom;

  // Determine parent compound under cursor (deepest).
  let parent: string | undefined;
  const parents = cy.nodes('.subgraph');
  let bestArea = Number.POSITIVE_INFINITY;
  parents.forEach((n) => {
    const bb = n.boundingBox();
    if (x < bb.x1 || x > bb.x2 || y < bb.y1 || y > bb.y2) return;
    const area = (bb.x2 - bb.x1) * (bb.y2 - bb.y1);
    if (area < bestArea) {
      bestArea = area;
      parent = n.id();
    }
  });

  emit('dropComponent', { componentType, x, y, parent });
}

const parentByName = computed(() => {
  const out: Record<string, string | undefined> = {};
  const nodes = Array.isArray(props.graph?.Nodes) ? props.graph.Nodes : [];
  for (const n of nodes) {
    if (!n || typeof n !== 'object') continue;
    const name = String((n as any).name || '').trim();
    if (!name) continue;
    const parentRaw = (n as any).parent;
    out[name] = typeof parentRaw === 'string' && parentRaw.trim() ? parentRaw.trim() : undefined;
  }
  return out;
});

const contextMoveOut = computed(() => {
  const id = contextMenu.value.nodeId;
  if (!contextMenu.value.visible || !id) return { ok: false, nextParent: undefined as string | undefined };
  const { base, suffix } = parseEndpoint(id);
  if (!base || suffix) return { ok: false, nextParent: undefined as string | undefined };
  const curParent = parentByName.value[base];
  if (!curParent) return { ok: false, nextParent: undefined as string | undefined };
  const next = parentByName.value[curParent];
  return { ok: true, nextParent: next };
});

function ctxAddOutgoing() {
  const id = contextMenu.value.nodeId;
  closeContextMenu();
  if (!id) return;
  startEdgeMode('from', id);
}

function ctxAddIncoming() {
  const id = contextMenu.value.nodeId;
  closeContextMenu();
  if (!id) return;
  startEdgeMode('to', id);
}

function ctxMoveOut() {
  const id = contextMenu.value.nodeId;
  closeContextMenu();
  if (!id) return;
  const { base, suffix } = parseEndpoint(id);
  if (!base || suffix) return;
  const curParent = parentByName.value[base];
  if (!curParent) return;
  const nextParent = parentByName.value[curParent];
  emit('nodeParentChanged', { nodeId: base, parent: nextParent });
}

const debugSummary = computed(() => {
  const nodes = Array.isArray(props.graph?.Nodes) ? props.graph.Nodes.length : 0;
  const edges = Array.isArray(props.graph?.Edges) ? props.graph.Edges.length : 0;
  return `${nodes} nodes · ${edges} edges`;
});

function graphRenderSignature(graph: VibeGraphDesign): string {
  try {
    const nodes = Array.isArray(graph?.Nodes) ? graph.Nodes : [];
    const nodeParts = nodes
      .map((n) => {
        const name = String((n as any)?.name || '');
        if (!name) return '';
        const type = String((n as any)?.type || '');
        const parent = typeof (n as any)?.parent === 'string' ? String((n as any).parent) : '';
        return `${name}|${type}|${parent}`;
      })
      .filter(Boolean)
      .sort();

    const edges = Array.isArray(graph?.Edges) ? graph.Edges : [];
    const edgeParts = edges
      .map((e) => {
        const from = String((e as any)?.from || '');
        const to = String((e as any)?.to || '');
        if (!from || !to) return '';
        const keys = (e as any)?.keys;
        const keyNames = Array.isArray(keys)
          ? keys.map((k: any) => String(k)).filter(Boolean).sort()
          : keys && typeof keys === 'object' && !Array.isArray(keys)
            ? Object.keys(keys as Record<string, unknown>).sort()
            : [];
        return `${from}->${to}|${keyNames.join(',')}`;
      })
      .filter(Boolean)
      .sort();

    return `${nodeParts.join(';')}||${edgeParts.join(';')}`;
  } catch {
    try {
      return JSON.stringify(graph);
    } catch {
      return String(graph);
    }
  }
}

function layoutRenderSignature(layout?: VibeLayout): string {
  const raw = layout && typeof layout === 'object' ? layout : {};
  try {
    return Object.entries(raw)
      .map(([id, p]) => {
        const x = typeof p?.x === 'number' && Number.isFinite(p.x) ? Math.round(p.x) : 0;
        const y = typeof p?.y === 'number' && Number.isFinite(p.y) ? Math.round(p.y) : 0;
        return `${id}:${x},${y}`;
      })
      .sort()
      .join('|');
  } catch {
    try {
      return JSON.stringify(raw);
    } catch {
      return String(raw);
    }
  }
}

const graphSig = computed(() => graphRenderSignature(props.graph));
const layoutSig = computed(() => layoutRenderSignature(props.layout));

watch(
  () => [props.docUri || '', graphSig.value, layoutSig.value] as const,
  () => {
    render();
  },
  { deep: false }
);

onMounted(() => {
  render();
});

onBeforeUnmount(() => {
  try {
    if (pendingResizeRaf !== null) cancelAnimationFrame(pendingResizeRaf);
  } catch {
    // ignore
  }
  pendingResizeRaf = null;
  try {
    if (dragRaf !== null) cancelAnimationFrame(dragRaf);
  } catch {
    // ignore
  }
  dragRaf = null;
  try {
    if (ghostRaf !== null) cancelAnimationFrame(ghostRaf);
  } catch {
    // ignore
  }
  ghostRaf = null;
  try {
    resizeObserver?.disconnect();
  } catch {
    // ignore
  }
  resizeObserver = null;
  try {
    if (edgeModeKeydown) {
      window.removeEventListener('keydown', edgeModeKeydown);
    }
  } catch {
    // ignore
  }
  edgeModeKeydown = null;
  try {
    if (stabilizeTimer !== null) clearTimeout(stabilizeTimer);
  } catch {
    // ignore
  }
  stabilizeTimer = null;
  try {
    cy?.destroy();
  } catch {
    // ignore
  }
  cy = null;
});
</script>

<template>
  <div
    ref="rootRef"
    class="root"
    @dragover="onDragOver"
    @drop="onDrop"
    @mousemove="onMouseMove"
    @mousedown="closeContextMenu"
  >
    <div class="status mono">
      <div>{{ debugSummary }}</div>
      <div class="muted">{{ cyStatus }}</div>
    </div>
    <div class="controls">
      <button class="ctl mono" type="button" @click="fitView">Fit</button>
      <button class="ctl mono" type="button" @click="relayoutAndFit('force')">Relayout</button>
    </div>
    <div v-if="dragHint" class="drag-hint mono">{{ dragHint }}</div>
    <div v-if="edgeModeActive" class="edge-mode">
      <div class="edge-mode-title mono">Edge mode</div>
      <div class="edge-mode-sub mono">{{ edgeModeTitle }}: {{ edgeModeAnchorId || '—' }}</div>
      <div class="edge-mode-sub mono">{{ edgeModeSubtitle }}</div>
      <button class="edge-mode-close" title="Cancel (Esc)" @click="cancelEdgeMode">×</button>
    </div>

    <div
      v-if="contextMenu.visible"
      class="ctx-menu"
      :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
      @mousedown.stop
    >
      <button class="ctx-item mono" type="button" @click="ctxAddOutgoing">Add outgoing edge</button>
      <button class="ctx-item mono" type="button" @click="ctxAddIncoming">Add incoming edge</button>
      <button
        v-if="contextMoveOut.ok"
        class="ctx-item mono"
        type="button"
        @click="ctxMoveOut"
      >
        Move out of subgraph
      </button>
    </div>

    <div v-if="renderError" class="error mono">
      <div class="error-title">Graph render error</div>
      <pre class="error-body">{{ renderError }}</pre>
    </div>

    <div ref="containerRef" class="cy"></div>
  </div>
</template>

<style scoped>
.root {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  overflow: hidden;
  background: var(--vscode-editor-background);
}

.cy {
  position: absolute;
  inset: 0;
}

.status {
  position: absolute;
  top: 34px;
  right: 8px;
  z-index: 10;
  padding: 3px 6px;
  font-size: 11px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.08);
  pointer-events: none;
}

.controls {
  position: absolute;
  top: 6px;
  right: 8px;
  z-index: 11;
  display: flex;
  gap: 6px;
}

.ctl {
  font-size: 11px;
  padding: 3px 7px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(0, 0, 0, 0.25);
  color: var(--vscode-editor-foreground);
  cursor: pointer;
}

.ctl:hover {
  background: rgba(255, 255, 255, 0.08);
}

.error {
  position: absolute;
  left: 8px;
  bottom: 8px;
  right: 8px;
  z-index: 30;
  border-radius: 8px;
  border: 1px solid rgba(244, 135, 113, 0.35);
  background: rgba(244, 135, 113, 0.1);
  padding: 10px;
  max-height: 38%;
  overflow: auto;
}

.error-title {
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 6px;
}

.error-body {
  margin: 0;
  font-size: 11px;
  white-space: pre-wrap;
  opacity: 0.9;
}

.edge-mode {
  position: absolute;
  top: 6px;
  left: 8px;
  z-index: 20;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.42);
  border: 1px solid rgba(255, 255, 255, 0.12);
  min-width: 180px;
}

.edge-mode-title {
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 2px;
}

.edge-mode-sub {
  font-size: 11px;
  opacity: 0.85;
  padding-right: 18px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.edge-mode-close {
  position: absolute;
  top: 6px;
  right: 8px;
  width: 18px;
  height: 18px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: transparent;
  color: var(--vscode-editor-foreground);
  cursor: pointer;
}

.edge-mode-close:hover {
  background: rgba(255, 255, 255, 0.08);
}

.drag-hint {
  position: absolute;
  top: 6px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 15;
  padding: 6px 10px;
  font-size: 11px;
  border-radius: 8px;
  background: rgba(242, 204, 96, 0.12);
  border: 1px solid rgba(242, 204, 96, 0.35);
  color: #f2cc60;
  max-width: 70%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  pointer-events: none;
}

.ctx-menu {
  position: absolute;
  z-index: 40;
  min-width: 200px;
  padding: 6px;
  border-radius: 8px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  background: var(--vscode-editor-background);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}

.ctx-item {
  width: 100%;
  display: block;
  text-align: left;
  padding: 7px 8px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--vscode-editor-foreground);
  cursor: pointer;
  font-size: 12px;
}

.ctx-item:hover {
  background: rgba(255, 255, 255, 0.07);
}

.ctx-item:disabled {
  opacity: 0.6;
  cursor: default;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
}

.muted {
  opacity: 0.75;
  font-size: 10px;
  max-width: 520px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
