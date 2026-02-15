<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import cytoscape, { type Core, type EventObjectNode, type EventObjectEdge } from 'cytoscape';
import { ensureCyDagreRegistered } from '../utils/cyDagre';
import { buildPreviewElements } from '../utils/previewElements';
import { GraphAttrsOverlayManager } from '../utils/graphAttrsOverlay';
import { applySmartDagreLayout } from '../utils/cyLayoutPipeline';
import { createPreviewStyle, applyPreviewEdgeStyle, type EdgeStyleMode } from '../utils/previewStyles';
import { postMessage } from '../bridge/vscode';
import { usePreviewStore } from '../stores/preview';

const preview = usePreviewStore();

const props = defineProps<{ visible: boolean }>();

const cyContainer = ref<HTMLDivElement | null>(null);
const overlayContainer = ref<HTMLDivElement | null>(null);
let cy: Core | null = null;
let overlayMgr: GraphAttrsOverlayManager | null = null;
let pendingRender = false;

const MAX_LOOP_ITERATIONS = 8;
const adjacencyPlaceholder =
  'Enter edges in format:\nfrom_index, to_index, keys\nExample:\n1, 2, {"data": "input"}\n2, 3, {"processed": "result"}';

const currentDocState = computed(() => preview.currentDocState);
const currentEdgeStyle = computed<EdgeStyleMode>(() => (currentDocState.value?.edgeStyle as EdgeStyleMode) || 'fan');

const templateCandidates = computed<string[]>(() => {
  const raw = (preview.graph as any)?.templateCandidates;
  if (!Array.isArray(raw)) return [];
  return raw.filter((x: any) => typeof x === 'string' && x.trim()).map((x: any) => String(x).trim());
});
const selectedTemplate = computed<string>(() => currentDocState.value?.templateName || '');

const isReadyToRender = computed(() => !!preview.graph && !!preview.documentUri);
const loadingText = computed(() => preview.clearReason || 'Waiting for Python code…');
const allWarnings = computed<string[]>(() => {
  const w1 = Array.isArray(preview.loopWarnings) ? preview.loopWarnings : [];
  const w2Raw = (preview.graph as any)?.warnings;
  const w2 = Array.isArray(w2Raw) ? w2Raw.filter((x: any) => typeof x === 'string') : [];
  return [...w1, ...w2];
});

type AdjacencyDraft = { text: string; error: string | null };
const adjacencyDrafts = reactive<Record<string, AdjacencyDraft>>({});

function ensureAdjacencyDraft(graphVariable: string): AdjacencyDraft {
  if (!adjacencyDrafts[graphVariable]) adjacencyDrafts[graphVariable] = { text: '', error: null };
  return adjacencyDrafts[graphVariable]!;
}

function formatConditionLabel(conditionId: string): string {
  const m = String(conditionId).match(/^if_(\d+)(?:_(.*))?$/s);
  if (m) {
    const line = m[1];
    const expr = (m[2] || '').replace(/\s+/g, ' ').trim();
    return expr ? `If (L${line}): ${expr}` : `If (L${line})`;
  }
  return conditionId;
}

function formatLoopLabel(loopId: string, info: { label?: string; variable?: string } | null): string {
  if (info?.label) return info.label;
  const m = String(loopId).match(/^for_(\d+)_/);
  if (m) return `for @L${m[1]}: ${info?.variable || 'i'} in …`;
  return loopId;
}

function getDocUri(): string | null {
  return preview.documentUri || null;
}

function formatTemplateName(name: string): string {
  const s = String(name || '').trim();
  if (!s) return '(unknown)';
  return s.includes('.') ? s.split('.').pop() || s : s;
}

function onTemplateChanged(next: string): void {
  const templateName = typeof next === 'string' ? next.trim() : '';
  preview.setTemplateName(templateName || null);
  postMessage({
    type: 'templateSelectionChanged',
    documentUri: getDocUri() || undefined,
    templateName: templateName || null
  });
}

function collectConditions(): Record<string, boolean> {
  const st = currentDocState.value;
  return st?.conditions ? { ...st.conditions } : {};
}

function onConditionChanged(conditionId: string, nextValue: boolean): void {
  const next = { ...collectConditions(), [conditionId]: nextValue };
  preview.setConditions(next);
  postMessage({ type: 'conditionChanged', documentUri: getDocUri() || undefined, conditions: next });
}

function collectLoopIterations(): Record<string, number> {
  const st = currentDocState.value;
  return st?.loopIterations ? { ...st.loopIterations } : {};
}

function onLoopIterationsApply(): void {
  const conditions = collectConditions();
  const loopIterations = collectLoopIterations();
  preview.setLoopIterations(loopIterations);
  postMessage({
    type: 'loopIterationsChanged',
    documentUri: getDocUri() || undefined,
    loopIterations,
    conditions
  });
}

function resetViewState(): void {
  preview.resetCurrentDocumentState();
  postMessage({ type: 'resetViewState', documentUri: getDocUri() || undefined });
}

function refreshGraph(): void {
  postMessage({ type: 'refreshGraph', documentUri: getDocUri() || undefined });
}

function onEdgeStyleChanged(mode: EdgeStyleMode): void {
  preview.setEdgeStyle(mode);
  if (cy) {
    try {
      applyPreviewEdgeStyle(cy, mode, preview.settings);
    } catch {
      // ignore
    }
  }
}

function formatAdjacencyEdges(
  edges: Array<{ from: number; to: number; keys?: Record<string, string> }>
): string {
  return edges
    .map((e) => {
      const keysStr = e.keys && Object.keys(e.keys).length > 0 ? `, ${JSON.stringify(e.keys)}` : '';
      return `${e.from}, ${e.to}${keysStr}`;
    })
    .join('\n');
}

function parseAdjacencyEdges(text: string): { edges: Array<{ from: number; to: number; keys?: Record<string, string> }>; error: string | null } {
  const lines = String(text)
    .trim()
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);

  const edges: Array<{ from: number; to: number; keys?: Record<string, string> }> = [];
  for (const line of lines) {
    const match = line.match(/^\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*(\{.*\}))?\s*$/);
    if (!match) return { edges: [], error: `Invalid line: ${line}` };
    const from = Number.parseInt(match[1], 10);
    const to = Number.parseInt(match[2], 10);
    /** @type {Record<string, string>} */
    let keys: Record<string, string> | undefined = undefined;
    if (match[3]) {
      try {
        const raw = JSON.parse(match[3]);
        if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
          keys = {};
          for (const [k, v] of Object.entries(raw)) keys[String(k)] = v === null || v === undefined ? '' : String(v);
        }
      } catch (err) {
        return { edges: [], error: `Failed to parse keys JSON: ${String(err)}` };
      }
    }
    edges.push(keys ? { from, to, keys } : { from, to });
  }
  return { edges, error: null };
}

function onAdjacencyApply(graphVariable: string): void {
  const draft = ensureAdjacencyDraft(graphVariable);
  const parsed = parseAdjacencyEdges(draft.text);
  draft.error = parsed.error;
  if (parsed.error) return;

  preview.setAdjacencyGraphEdges(graphVariable, parsed.edges);

  postMessage({
    type: 'adjacencyGraphChanged',
    documentUri: getDocUri() || undefined,
    graphVariable,
    edges: parsed.edges,
    conditions: collectConditions(),
    loopIterations: collectLoopIterations()
  });
}

function hideDescendants(nodeId: string): void {
  if (!cy) return;
  const node = cy.getElementById(nodeId);
  if (!node || node.empty()) return;
  try {
    node.descendants().forEach((d) => d.style('display', 'none'));
  } catch {
    // ignore
  }
}

function showDescendants(nodeId: string): void {
  if (!cy) return;
  const node = cy.getElementById(nodeId);
  if (!node || node.empty()) return;
  try {
    node.descendants().forEach((d) => d.style('display', 'element'));
  } catch {
    // ignore
  }
}

function applyCollapsedVisibility(): void {
  const st = currentDocState.value;
  if (!cy || !st?.collapsedSubgraphs) return;
  for (const [nodeId, isCollapsed] of Object.entries(st.collapsedSubgraphs)) {
    if (!isCollapsed) continue;
    const node = cy.getElementById(nodeId);
    if (!node || node.empty() || !node.isParent()) continue;
    node.addClass('collapsed');
    hideDescendants(nodeId);
  }
}

function applyPreviewLayout(): void {
  if (!cy) return;
  try {
    applySmartDagreLayout(cy, { preferDirection: 'AUTO', fitPadding: 50, dagreRankDir: 'TB', dagreNodeSep: 40, dagreRankSep: 65 });
  } catch {
    // ignore
  }
}

function isCanvasVisible(): boolean {
  const w = cyContainer.value?.clientWidth ?? 0;
  const h = cyContainer.value?.clientHeight ?? 0;
  return w >= 20 && h >= 20;
}

function canRenderNow(): boolean {
  return !!props.visible && isCanvasVisible();
}

function restoreCachedPositions(hasPositionsCache: boolean): void {
  if (!cy || !hasPositionsCache) return;
  const st = currentDocState.value;
  const pos = st?.positions || {};
  cy.batch(() => {
    for (const [nodeId, p] of Object.entries(pos)) {
      const n = cy!.getElementById(nodeId);
      if (!n || n.empty() || !n.isNode()) continue;
      if (n.isParent && n.isParent()) continue;
      const x = Number((p as any).x);
      const y = Number((p as any).y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      try {
        n.position({ x, y });
      } catch {
        // ignore
      }
    }
  });
}

function restoreViewportOrFit(hasViewportCache: boolean): void {
  if (!cy) return;
  const st = currentDocState.value;
  if (hasViewportCache && st?.pan && typeof st.zoom === 'number') {
    try {
      cy.zoom(st.zoom);
      cy.pan(st.pan);
    } catch {
      // ignore
    }
    return;
  }
  try {
    cy.fit(cy.elements(), 50);
  } catch {
    // ignore
  }
}

function cacheBaselineLayout(hasPositionsCache: boolean, hasViewportCache: boolean): void {
  if (!cy) return;
  const st = currentDocState.value;
  if (!st) return;

  const shouldStoreAll = !hasPositionsCache;
  /** @type {Record<string, {x:number;y:number}>} */
  const nextPositions: Record<string, { x: number; y: number }> = {};
  cy.nodes().forEach((n) => {
    if (n.isParent && n.isParent()) return;
    if (!shouldStoreAll && st.positions && st.positions[n.id()]) return;
    const p = n.position();
    if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) return;
    nextPositions[n.id()] = { x: p.x, y: p.y };
  });
  if (Object.keys(nextPositions).length > 0) {
    preview.mergeNodePositions(nextPositions, { overwrite: shouldStoreAll });
  }

  if (!hasViewportCache) {
    try {
      preview.setViewport(cy.zoom(), cy.pan());
    } catch {
      // ignore
    }
  }
}

function renderGraph(): void {
  if (!cy) return;
  const graph = preview.graph;
  const uri = preview.documentUri;
  if (!graph || !uri) return;

  const st = currentDocState.value;
  const hasPositionsCache = !!(st?.positions && Object.keys(st.positions).length > 0);
  const hasViewportCache = !!(st && typeof st.zoom === 'number' && st.pan && typeof st.pan.x === 'number' && typeof st.pan.y === 'number');

  const collapsedSubgraphs = (st?.collapsedSubgraphs as Record<string, boolean> | undefined) || {};
  const elements = buildPreviewElements(graph, { collapsedSubgraphs });

  cy.batch(() => {
    cy!.elements().remove();
    cy!.add(elements as any);
  });

  try {
    cy.style(createPreviewStyle(preview.settings, currentEdgeStyle.value));
  } catch {
    // ignore
  }

  try {
    applyPreviewEdgeStyle(cy, currentEdgeStyle.value, preview.settings);
  } catch {
    // ignore
  }

  applyCollapsedVisibility();
  applyPreviewLayout();
  restoreCachedPositions(hasPositionsCache);
  restoreViewportOrFit(hasViewportCache);
  cacheBaselineLayout(hasPositionsCache, hasViewportCache);

  // Sync adjacency drafts from persisted state (best-effort).
  const adjacency = st?.adjacencyGraphs || {};
  for (const [graphVariable, state] of Object.entries(adjacency)) {
    const draft = ensureAdjacencyDraft(graphVariable);
    if (!draft.text) {
      draft.text = formatAdjacencyEdges((state as any).edges || []);
    }
  }

  overlayMgr?.rebuild(graph);
}

function tryRenderGraph(): void {
  if (!cy) return;
  if (!isReadyToRender.value) return;
  if (!canRenderNow()) {
    pendingRender = true;
    return;
  }
  pendingRender = false;
  renderGraph();
}

function toggleSubgraph(nodeId: string): void {
  if (!cy) return;
  const st = currentDocState.value;
  if (!st) return;
  const node = cy.getElementById(nodeId);
  if (!node || node.empty() || !node.isParent()) return;

  const isCollapsed = !!st.collapsedSubgraphs?.[nodeId];
  if (isCollapsed) {
    preview.setCollapsedSubgraph(nodeId, false);
    node.removeClass('collapsed');
    showDescendants(nodeId);
  } else {
    preview.setCollapsedSubgraph(nodeId, true);
    node.addClass('collapsed');
    hideDescendants(nodeId);
  }

  const hasPositionsCache = !!(st.positions && Object.keys(st.positions).length > 0);
  const hasViewportCache = !!(typeof st.zoom === 'number' && st.pan && typeof st.pan.x === 'number' && typeof st.pan.y === 'number');
  if (!hasPositionsCache) {
    applyPreviewLayout();
    if (!hasViewportCache) {
      try {
        cy.fit(cy.elements(), 50);
      } catch {
        // ignore
      }
    }
  }
  overlayMgr?.scheduleUpdate('all');
}

function isInternalNodeId(nodeId: string, nodeType: string): boolean {
  if (nodeId === 'entry' || nodeId === 'exit') return true;
  if (nodeType === 'entry' || nodeType === 'exit') return true;
  if (nodeId.endsWith('_entry') || nodeId.endsWith('_exit')) return true;
  if (nodeType === 'Controller' || nodeType === 'TerminateNode') return true;
  if (nodeId.endsWith('_controller') || nodeId.endsWith('_terminate')) return true;
  return false;
}

function navigateToNode(nodeId: string): void {
  const graph = preview.graph as any;
  const uri = preview.documentUri;
  if (!graph || !uri) return;
  const line = graph.nodeLineNumbers?.[nodeId];
  if (!line) return;
  const targetUri = graph.nodeFilePaths?.[nodeId] || uri;
  postMessage({ type: 'navigateToLine', uri: targetUri, lineNumber: line });
}

function navigateToEdge(edgeId: string): void {
  const graph = preview.graph as any;
  const uri = preview.documentUri;
  if (!graph || !uri) return;
  const edges = Array.isArray(graph.edges) ? graph.edges : [];
  const baseId = String(edgeId || '').split('#')[0] || edgeId;
  const match = edges.find((e: any) => `${e.from}-${e.to}` === baseId);
  if (!match || !match.lineNumber) return;
  const targetUri = match.filePath || uri;
  postMessage({ type: 'navigateToLine', uri: targetUri, lineNumber: match.lineNumber });
}

function attachCyHandlers(): void {
  if (!cy) return;

  // Toggle subgraphs.
  cy.on('dblclick', 'node:parent', (evt: EventObjectNode) => {
    try {
      toggleSubgraph(evt.target.id());
    } catch {
      // ignore
    }
  });

  // Tooltip state shared by node/edge hovers.
  let tooltip: HTMLDivElement | null = null;
  let mousemoveHandler: ((e: any) => void) | null = null;

  const clearTooltip = () => {
    if (tooltip) {
      tooltip.remove();
      tooltip = null;
    }
    if (mousemoveHandler) {
      try {
        cy?.off('mousemove', mousemoveHandler);
      } catch {
        // ignore
      }
      mousemoveHandler = null;
    }
  };

  cy.on('mouseover', 'node', (evt: EventObjectNode) => {
    const node = evt.target;
    const nodeType = String(node.data('type') || 'Node');
    const nodeName = node.id();
    const pullKeys = node.data('pullKeys');
    const pushKeys = node.data('pushKeys');
    const attributes = node.data('attributes');
    const aliases = node.data('aliases');

    node.addClass('hovered-node');

    const outgoing = node.connectedEdges().filter((e) => e.source().id() === node.id());
    const incoming = node.connectedEdges().filter((e) => e.target().id() === node.id());

    const setHoveredLabel = (edge: any, mode: 'hovered-edge' | 'incoming-edge') => {
      edge.addClass(mode);
      const displayParts: string[] = [];
      const variableName = edge.data('variableName');
      const keysList = edge.data('keysList');
      if (variableName) displayParts.push(String(variableName));
      if (keysList) displayParts.push(String(keysList));
      edge.data('displayLabel', displayParts.join(' • '));
    };
    outgoing.forEach((e) => setHoveredLabel(e, 'hovered-edge'));
    incoming.forEach((e) => setHoveredLabel(e, 'incoming-edge'));

    clearTooltip();

    let content = '<div class="tooltip-header">';
    content += `<div class="tooltip-row"><span class="tooltip-label">Name:</span> <span class="tooltip-value">${nodeName}</span></div>`;
    content += `<div class="tooltip-row"><span class="tooltip-label">Type:</span> <span class="tooltip-value">${nodeType}</span></div>`;
    if (aliases && Array.isArray(aliases) && aliases.length > 0) {
      content += `<div class="tooltip-row"><span class="tooltip-label">Aliases:</span> <span class="tooltip-value">${aliases.join(
        ', '
      )}</span></div>`;
    }
    content += '</div>';

    content += '<div class="tooltip-section">';
    content += '<div class="tooltip-section-title pull-keys-title">📥 Pull Keys</div>';
    if (pullKeys !== undefined) {
      if (pullKeys === 'empty') {
        content += '<div class="tooltip-empty">{} <span class="tooltip-hint">(no inheritance)</span></div>';
      } else if (pullKeys === null) {
        content += '<div class="tooltip-empty">None <span class="tooltip-hint">(inherit all)</span></div>';
      } else if (typeof pullKeys === 'object' && Object.keys(pullKeys).length > 0) {
        for (const [key, desc] of Object.entries(pullKeys)) {
          content += '<div class="tooltip-kv-pair">';
          content += `<span class="tooltip-key">${key}:</span> `;
          content += `<span class="tooltip-desc">${String(desc)}</span>`;
          content += '</div>';
        }
      } else {
        content += '<div class="tooltip-empty">None <span class="tooltip-hint">(inherit all)</span></div>';
      }
    } else if (nodeType === 'Agent' || nodeType === 'DynamicAgent') {
      content += '<div class="tooltip-empty">{} <span class="tooltip-hint">(default for Agent)</span></div>';
    } else {
      content += '<div class="tooltip-empty">None <span class="tooltip-hint">(default, inherit all)</span></div>';
    }
    content += '</div>';

    content += '<div class="tooltip-section">';
    content += '<div class="tooltip-section-title push-keys-title">📤 Push Keys</div>';
    if (pushKeys !== undefined) {
      if (pushKeys === 'empty') {
        content += '<div class="tooltip-empty">{} <span class="tooltip-hint">(no push)</span></div>';
      } else if (pushKeys === null) {
        content += '<div class="tooltip-empty">None <span class="tooltip-hint">(push all)</span></div>';
      } else if (typeof pushKeys === 'object' && Object.keys(pushKeys).length > 0) {
        for (const [key, desc] of Object.entries(pushKeys)) {
          content += '<div class="tooltip-kv-pair">';
          content += `<span class="tooltip-key">${key}:</span> `;
          content += `<span class="tooltip-desc">${String(desc)}</span>`;
          content += '</div>';
        }
      } else {
        content += '<div class="tooltip-empty">None <span class="tooltip-hint">(push all)</span></div>';
      }
    } else if (nodeType === 'Agent' || nodeType === 'DynamicAgent') {
      content += '<div class="tooltip-empty">{} <span class="tooltip-hint">(default for Agent)</span></div>';
    } else {
      content += '<div class="tooltip-empty">None <span class="tooltip-hint">(default, push all)</span></div>';
    }
    content += '</div>';

    if (attributes !== undefined && attributes !== null) {
      content += '<div class="tooltip-section">';
      content += '<div class="tooltip-section-title attributes-title">⚙️ Attributes</div>';
      if (typeof attributes === 'object' && Object.keys(attributes).length > 0) {
        for (const [key, value] of Object.entries(attributes)) {
          let valueStr = '';
          if (typeof value === 'string') valueStr = `"${value}"`;
          else if (value === null) valueStr = 'null';
          else if (typeof value === 'object') valueStr = JSON.stringify(value);
          else valueStr = String(value);
          content += '<div class="tooltip-kv-pair">';
          content += `<span class="tooltip-key">${key}:</span> `;
          content += `<span class="tooltip-attr-value">${valueStr}</span>`;
          content += '</div>';
        }
      } else {
        content += '<div class="tooltip-empty">{}</div>';
      }
      content += '</div>';
    }

    tooltip = document.createElement('div');
    tooltip.className = 'cy-tooltip';
    tooltip.innerHTML = content;
    document.body.appendChild(tooltip);

    mousemoveHandler = (e: any) => {
      if (!tooltip) return;
      tooltip.style.left = `${e.renderedPosition.x + 15}px`;
      tooltip.style.top = `${e.renderedPosition.y + 15}px`;
    };
    mousemoveHandler(evt as any);
    cy.on('mousemove', mousemoveHandler);
  });

  cy.on('mouseout', 'node', (evt: EventObjectNode) => {
    clearTooltip();
    const node = evt.target;
    node.removeClass('hovered-node');

    const restore = (edge: any) => {
      edge.removeClass('hovered-edge');
      edge.removeClass('incoming-edge');
      const original = edge.data('originalDisplayLabel');
      edge.data('displayLabel', original || '');
    };

    node
      .connectedEdges()
      .filter((e) => e.source().id() === node.id() || e.target().id() === node.id())
      .forEach((e) => restore(e));
  });

  cy.on('mouseover', 'edge', (evt: EventObjectEdge) => {
    const edge = evt.target;
    const keysDetails = edge.data('keysDetails');
    const variableName = edge.data('variableName');
    const keysList = edge.data('keysList');
    const source = edge.data('source');
    const target = edge.data('target');

    edge.addClass('hovered-edge');
    const displayParts: string[] = [];
    if (variableName) displayParts.push(String(variableName));
    if (keysList) displayParts.push(String(keysList));
    edge.data('displayLabel', displayParts.join(' • '));

    edge.source()?.addClass('hovered-node');
    edge.target()?.addClass('hovered-node');

    clearTooltip();
    tooltip = document.createElement('div');
    tooltip.className = 'cy-tooltip';

    let content = '';
    content += `<strong>Edge:</strong> ${String(source)} → ${String(target)}<br/>`;
    if (variableName) content += `<strong>Variable:</strong> ${String(variableName)}<br/>`;
    if (keysDetails && typeof keysDetails === 'object' && Object.keys(keysDetails).length > 0) {
      content += '<strong>Keys:</strong><br/>';
      for (const [k, v] of Object.entries(keysDetails)) {
        content += `&nbsp;&nbsp;${String(k)}: ${String(v)}<br/>`;
      }
    } else {
      content += '<strong>Keys:</strong> (empty)<br/>';
    }
    tooltip.innerHTML = content;
    document.body.appendChild(tooltip);

    mousemoveHandler = (e: any) => {
      if (!tooltip) return;
      tooltip.style.left = `${e.renderedPosition.x + 15}px`;
      tooltip.style.top = `${e.renderedPosition.y + 15}px`;
    };
    mousemoveHandler(evt as any);
    cy.on('mousemove', mousemoveHandler);
  });

  cy.on('mouseout', 'edge', (evt: EventObjectEdge) => {
    clearTooltip();
    const edge = evt.target;
    edge.removeClass('hovered-edge');
    const original = edge.data('originalDisplayLabel');
    edge.data('displayLabel', original || '');
    edge.source()?.removeClass('hovered-node');
    edge.target()?.removeClass('hovered-node');
  });

  cy.container()?.addEventListener('mouseleave', () => clearTooltip());

  cy.on('click', 'node', (evt: EventObjectNode) => {
    const n = evt.target;
    const nodeId = n.id();
    const nodeType = String(n.data('type') || 'Node');
    if (n.isParent && n.isParent()) return;
    if (isInternalNodeId(nodeId, nodeType)) return;
    navigateToNode(nodeId);
  });

  cy.on('click', 'edge', (evt: EventObjectEdge) => {
    const e = evt.target;
    navigateToEdge(e.id());
  });

  cy.on('pan zoom', () => {
    overlayMgr?.scheduleUpdate('all');
    try {
      preview.setViewport(cy!.zoom(), cy!.pan());
    } catch {
      // ignore
    }
  });

  cy.on('drag', 'node', (evt: EventObjectNode) => {
    try {
      const n = evt.target;
      const affected: string[] = [];
      if (n.isParent && n.isParent()) {
        affected.push(n.id());
      } else {
        n.parents().forEach((p) => affected.push(p.id()));
      }
      if (affected.length > 0) overlayMgr?.scheduleUpdate(affected);
    } catch {
      // ignore
    }
  });

  cy.on('dragfree', 'node', (evt: EventObjectNode) => {
    try {
      const n = evt.target;
      const positions: Record<string, { x: number; y: number }> = {};
      const storePos = (nodeEl: any) => {
        if (!nodeEl || !nodeEl.isNode || !nodeEl.isNode()) return;
        const p = nodeEl.position();
        if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) return;
        positions[nodeEl.id()] = { x: p.x, y: p.y };
      };
      if (n.isParent && n.isParent()) {
        n.descendants().forEach((child: any) => storePos(child));
      } else {
        storePos(n);
      }
      if (Object.keys(positions).length > 0) preview.mergeNodePositions(positions, { overwrite: true });
    } catch {
      // ignore
    }
  });
}

onMounted(() => {
  ensureCyDagreRegistered();
  if (!cyContainer.value) return;

  cy = cytoscape({
    container: cyContainer.value,
    elements: [],
    style: createPreviewStyle(preview.settings, currentEdgeStyle.value),
    layout: { name: 'preset' },
    minZoom: 0.3,
    maxZoom: 3,
    wheelSensitivity: 1.5
  });

  if (overlayContainer.value) {
    overlayMgr = new GraphAttrsOverlayManager({
      container: overlayContainer.value,
      getDocState: () => (currentDocState.value ? { overlayCollapsed: currentDocState.value.overlayCollapsed } : null),
      setCollapsed: (graphId, collapsed) => preview.setOverlayCollapsed(graphId, collapsed)
    });
    overlayMgr.attach(cy);
  }

  attachCyHandlers();

  void nextTick().then(() => {
    try {
      cy?.resize();
    } catch {
      // ignore
    }
    tryRenderGraph();
  });
});

onBeforeUnmount(() => {
  overlayMgr?.dispose();
  overlayMgr = null;
  try {
    cy?.destroy();
  } catch {
    // ignore
  }
  cy = null;
});

watch(
  () => [preview.graph, preview.documentUri],
  async () => {
    await nextTick();
    if (!cy) return;
    tryRenderGraph();
  }
);

watch(
  () => [preview.settings, currentEdgeStyle.value],
  async () => {
    await nextTick();
    if (!cy) return;
    try {
      cy.style(createPreviewStyle(preview.settings, currentEdgeStyle.value));
      applyPreviewEdgeStyle(cy, currentEdgeStyle.value, preview.settings);
    } catch {
      // ignore
    }
  },
  { deep: true }
);

watch(
  () => preview.adjacencyGraphControls,
  () => {
    const st = currentDocState.value;
    if (!st) return;
    for (const graphVariable of Object.keys(preview.adjacencyGraphControls || {})) {
      const draft = ensureAdjacencyDraft(graphVariable);
      if (!draft.text) {
        const saved = st.adjacencyGraphs?.[graphVariable]?.edges || [];
        draft.text = formatAdjacencyEdges(saved as any);
      }
    }
  },
  { deep: true }
);

watch(
  () => props.visible,
  async (visible) => {
    if (!visible) return;
    await nextTick();
    requestAnimationFrame(() => {
      try {
        cy?.resize();
      } catch {
        // ignore
      }
      overlayMgr?.scheduleUpdate('all');
      if (pendingRender) {
        tryRenderGraph();
        return;
      }
      // Stabilize viewport when returning to a previously rendered graph.
      if (cy && isReadyToRender.value && isCanvasVisible()) {
        const st = currentDocState.value;
        const hasViewportCache = !!(
          st &&
          typeof st.zoom === 'number' &&
          st.pan &&
          typeof st.pan.x === 'number' &&
          typeof st.pan.y === 'number'
        );
        restoreViewportOrFit(hasViewportCache);
      }
    });
  }
);
</script>

<template>
  <div class="preview-root">
    <div id="loading" v-show="!isReadyToRender">{{ loadingText }}</div>

    <div id="controlPanel" v-show="isReadyToRender">
      <div id="viewSection" class="control-section">
        <h3>View</h3>
        <button id="refreshViewButton" title="Re-render graph without clearing cached layout/state" @click="refreshGraph">
          Refresh
        </button>
        <button id="resetViewButton" title="Clear cached layout/state for this file and reload" @click="resetViewState">
          Reset (Clear Cache)
        </button>
      </div>

      <div id="templateSection" class="control-section" v-show="templateCandidates.length > 1">
        <h3>Template</h3>
        <div class="control-item">
          <label for="templateSelect">NodeTemplate graph</label>
          <select
            id="templateSelect"
            :value="selectedTemplate"
            @change="(e:any)=>onTemplateChanged(String(e.target.value))"
          >
            <option v-for="t in templateCandidates" :key="t" :value="t">
              {{ formatTemplateName(t) }}
            </option>
          </select>
        </div>
      </div>

      <div id="conditionSection" class="control-section" v-show="preview.conditionVariables.length > 0">
        <h3>Conditional Branches</h3>
        <div id="conditionControls">
          <div v-for="condVar in preview.conditionVariables" :key="condVar" class="control-item">
            <label :title="condVar">{{ formatConditionLabel(condVar) }}</label>
            <select
              :value="String((currentDocState?.conditions?.[condVar] ?? true) ? 'true' : 'false')"
              @change="(e:any)=>onConditionChanged(condVar, String(e.target.value)==='true')"
            >
              <option value="true">True</option>
              <option value="false">False</option>
            </select>
          </div>
        </div>
      </div>

      <div id="loopSection" class="control-section" v-show="Object.keys(preview.loopControls).length > 0">
        <h3>Loop Iterations</h3>
        <div id="loopControls">
          <div v-for="(info, loopId) in preview.loopControls" :key="loopId" class="control-item">
            <label :title="info.label || String(loopId)">{{ formatLoopLabel(String(loopId), info) }}</label>
            <select
              :value="String(Math.max(1, Math.min(MAX_LOOP_ITERATIONS, Number(currentDocState?.loopIterations?.[loopId] ?? info.defaultIterations ?? 1))))"
              @change="(e:any)=>preview.setLoopIterations({ ...collectLoopIterations(), [loopId]: Number(e.target.value) })"
            >
              <option v-for="i in MAX_LOOP_ITERATIONS" :key="i" :value="String(i)">
                {{ i }} iteration{{ i > 1 ? 's' : '' }}
              </option>
            </select>
          </div>
        </div>
        <button id="loopApplyButton" @click="onLoopIterationsApply">Apply Loop Iterations</button>
      </div>

      <div
        id="adjacencyGraphSection"
        class="control-section"
        v-show="Object.keys(preview.adjacencyGraphControls).length > 0"
      >
        <h3>Adjacency Graphs</h3>
        <div id="adjacencyGraphControls">
          <div
            v-for="(control, graphVariable) in preview.adjacencyGraphControls"
            :key="graphVariable"
            class="adjacency-graph-item"
          >
            <div class="adjacency-graph-header">{{ control.label || graphVariable }}</div>
            <div class="adjacency-graph-edges">
              <div class="adjacency-node-info">
                <small>
                  Nodes:
                  {{
                    control.nodeInfo.map((n) => `${n.index}:${n.name}(${n.type})`).join(', ')
                  }}
                </small>
              </div>
              <textarea
                class="adjacency-edge-input"
                rows="5"
                :placeholder="adjacencyPlaceholder"
                :value="ensureAdjacencyDraft(String(graphVariable)).text"
                @input="(e:any)=>{ const d=ensureAdjacencyDraft(String(graphVariable)); d.text=e.target.value; d.error=null; }"
              />
              <div v-if="ensureAdjacencyDraft(String(graphVariable)).error" class="hint warn">
                {{ ensureAdjacencyDraft(String(graphVariable)).error }}
              </div>
              <button class="adjacency-apply-button" type="button" @click="onAdjacencyApply(String(graphVariable))">
                Apply Structure
              </button>
            </div>
          </div>
        </div>
      </div>

      <div id="edgeStyleSection" class="control-section" v-show="isReadyToRender">
        <h3>Edge Style</h3>
        <div class="control-item">
          <label for="edgeStyleSelect">Edge style</label>
          <select id="edgeStyleSelect" :value="currentEdgeStyle" @change="(e:any)=>onEdgeStyleChanged(e.target.value)">
            <option value="fan">Fan Out (default)</option>
            <option value="straight">Straight</option>
          </select>
        </div>
      </div>

      <div
        id="warningSection"
        class="control-section"
        v-show="allWarnings.length > 0"
      >
        <h3>Warnings</h3>
        <div id="warningList">
          <div v-for="(w, i) in allWarnings" :key="i" class="warning-item">
            {{ w }}
          </div>
        </div>
      </div>
    </div>

    <div id="cy" ref="cyContainer"></div>
    <div id="graphAttrsContainer" ref="overlayContainer"></div>
  </div>
</template>

<style>
.preview-root {
  width: 100%;
  height: 100%;
  position: relative;
  background-color: var(--vscode-editor-background);
  color: var(--vscode-editor-foreground);
  overflow: hidden;
}

#cy {
  width: 100%;
  height: 100%;
  position: absolute;
  top: 0;
  left: 0;
}

#loading {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 16px;
  color: var(--vscode-editor-foreground);
}

#controlPanel {
  position: absolute;
  top: 10px;
  left: 10px;
  width: 320px;
  max-height: calc(100% - 20px);
  overflow-y: auto;
  z-index: 1000;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  background: rgba(30, 30, 30, 0.95);
  color: var(--vscode-editor-foreground);
  font-size: 12px;
}

#controlPanel h3 {
  margin: 0 0 8px 0;
  font-size: 13px;
  font-weight: 600;
}

.control-section {
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.control-section:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}

.control-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}

.control-item label {
  font-size: 12px;
  opacity: 0.9;
}

.control-item select {
  width: 100%;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid var(--vscode-input-border, #2d2d2d);
  background: var(--vscode-input-background, rgba(255, 255, 255, 0.06));
  color: var(--vscode-input-foreground, #fff);
}

#controlPanel button,
.adjacency-apply-button {
  width: 100%;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--vscode-button-border, rgba(255, 255, 255, 0.12));
  background: var(--vscode-button-background, #0e639c);
  color: var(--vscode-button-foreground, #fff);
  cursor: pointer;
  font-size: 12px;
}

#controlPanel button:hover,
.adjacency-apply-button:hover {
  background: var(--vscode-button-hoverBackground, #1177bb);
}

#refreshViewButton,
#resetViewButton {
  margin-bottom: 8px;
}

.warning-item {
  margin-bottom: 6px;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(244, 135, 113, 0.12);
  border: 1px solid rgba(244, 135, 113, 0.35);
}

.hint.warn {
  margin: 6px 0;
  font-size: 12px;
  opacity: 0.9;
  color: #f2cc60;
}

/* Tooltip styles */
.cy-tooltip {
  position: absolute;
  z-index: 2000;
  max-width: 360px;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(30, 30, 30, 0.96);
  color: var(--vscode-editor-foreground);
  font-size: 12px;
  pointer-events: none;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
}

.tooltip-header {
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.12);
}

.tooltip-header .tooltip-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
}

.tooltip-header .tooltip-row:last-child {
  margin-bottom: 0;
}

.tooltip-label {
  font-weight: 600;
  opacity: 0.85;
}

.tooltip-value {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
  text-align: right;
  margin-left: 12px;
}

.tooltip-section {
  margin-bottom: 10px;
}

.tooltip-section:last-child {
  margin-bottom: 0;
}

.tooltip-section-title {
  font-weight: 700;
  margin-bottom: 6px;
  font-size: 12px;
}

.pull-keys-title {
  color: #4fc3f7;
}

.push-keys-title {
  color: #ba68c8;
}

.attributes-title {
  color: #81c784;
}

.tooltip-kv-pair {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
}

.tooltip-key {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
  font-weight: 600;
  opacity: 0.9;
}

.tooltip-desc,
.tooltip-attr-value {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
  opacity: 0.85;
  word-break: break-word;
}

.tooltip-empty {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
  opacity: 0.8;
}

.tooltip-hint {
  opacity: 0.7;
  margin-left: 6px;
}

/* Graph attributes overlay layer */
#graphAttrsContainer {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1500;
}

.graph-attrs-overlay {
  position: absolute;
  max-width: 280px;
  font-size: 11px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(30, 30, 30, 0.92);
  padding: 8px 10px;
  pointer-events: auto;
}

.graph-attrs-overlay.hidden {
  display: none;
}

.graph-attrs-overlay.graph-attrs-root {
  transform: none !important;
}

.graph-attrs-overlay.collapsed .graph-attrs-content {
  display: none;
}

.graph-attrs-overlay.collapsed .graph-attrs-header {
  margin-bottom: 0;
}

.graph-attrs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.graph-attrs-title {
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.graph-attrs-toggle {
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: transparent;
  color: var(--vscode-editor-foreground);
  border-radius: 6px;
  cursor: pointer;
  width: 26px;
  height: 22px;
  font-size: 12px;
  line-height: 18px;
}

.graph-attrs-toggle:hover {
  background: rgba(255, 255, 255, 0.06);
}

.graph-attrs-section {
  margin-bottom: 8px;
}

.graph-attrs-section-label {
  font-weight: 700;
  margin-bottom: 6px;
}

.graph-attrs-section-label.initial {
  color: #4fc3f7;
}

.graph-attrs-section-label.pull {
  color: #64b5f6;
}

.graph-attrs-section-label.runtime {
  color: #f2cc60;
}

.graph-attrs-section-label.push {
  color: #ba68c8;
}

.graph-attrs-key {
  display: inline-block;
  padding: 2px 6px;
  margin: 2px 4px 2px 0;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
}

.graph-attrs-key.initial {
  color: #4fc3f7;
}

.graph-attrs-key.pull {
  color: #64b5f6;
}

.graph-attrs-key.runtime {
  color: #f2cc60;
}

.graph-attrs-key.push {
  color: #ba68c8;
}

/* Adjacency controls */
.adjacency-graph-item {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 10px;
}

.adjacency-graph-header {
  font-weight: 700;
  margin-bottom: 8px;
}

.adjacency-graph-edges {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.adjacency-edge-input {
  width: 100%;
  box-sizing: border-box;
  border-radius: 6px;
  border: 1px solid var(--vscode-input-border, #2d2d2d);
  background: var(--vscode-input-background, rgba(255, 255, 255, 0.06));
  color: var(--vscode-input-foreground, #fff);
  padding: 6px 8px;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
  font-size: 11px;
}

.adjacency-node-info {
  opacity: 0.8;
}
</style>
