<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { type Core, type ElementDefinition, type Stylesheet } from 'cytoscape';
import type { GraphData } from '../types/graph';
import type { ExecutionState, NodeExecution } from '../types/runtimeExec';
import { ensureCyDagreRegistered } from '../utils/cyDagre';
import { applySmartDagreLayout } from '../utils/cyLayoutPipeline';
import { CyGraphRenderer } from '../utils/cyGraphRenderer';
import { buildGraphElements } from '../utils/graphElements.js';

ensureCyDagreRegistered();

const props = defineProps<{
  graph: GraphData | null;
  execution?: ExecutionState;
  selectedNodeId?: string | null;
  pausedNodeIds?: string[];
  exceptionNodeIds?: string[];
  waitingNodeIds?: string[];
}>();

const emit = defineEmits<{
  (e: 'selectNode', nodeId: string): void;
  (e: 'clearSelection'): void;
}>();

const containerRef = ref<HTMLDivElement | null>(null);
let lastGraphSig: string | null = null;

const hasGraph = computed(() => !!props.graph && props.graph.nodes?.length > 0);
const exec = computed<ExecutionState>(
  () => props.execution || { runningNodes: [], nodeHistory: {} }
);
const selectedNodeId = computed(() => props.selectedNodeId || null);
const pausedNodeIds = computed(() =>
  Array.isArray(props.pausedNodeIds) ? props.pausedNodeIds : []
);
const exceptionNodeIds = computed(() =>
  Array.isArray(props.exceptionNodeIds) ? props.exceptionNodeIds : []
);
const waitingNodeIds = computed(() =>
  Array.isArray(props.waitingNodeIds) ? props.waitingNodeIds : []
);

const tooltipVisible = ref(false);
const tooltipX = ref(0);
const tooltipY = ref(0);
const tooltipNodeId = ref<string>('');
const tooltipRuns = ref<NodeExecution[]>([]);

let glowRaf: number | null = null;
let lastGlowTick = 0;

function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function graphSig(graph: GraphData): string {
  const nodes = Array.isArray(graph.nodes) ? graph.nodes.map((n) => String(n)).sort() : [];
  const edges = Array.isArray(graph.edges)
    ? graph.edges
        .map((e: any) => {
          const from = typeof e?.from === 'string' ? e.from : '';
          const to = typeof e?.to === 'string' ? e.to : '';
          return from && to ? `${from}->${to}` : '';
        })
        .filter(Boolean)
        .sort()
    : [];
  return `${nodes.join('|')}::${edges.join('|')}`;
}

function stopGlow(): void {
  if (glowRaf !== null) {
    window.cancelAnimationFrame(glowRaf);
    glowRaf = null;
  }
  lastGlowTick = 0;
}

function tickGlow(now: number): void {
  const cy = renderer.getCy();
  if (!cy) {
    stopGlow();
    return;
  }
  const running = cy.nodes('.running');
  const waiting = cy.nodes('.waiting');
  if ((!running || running.empty()) && (!waiting || waiting.empty())) {
    stopGlow();
    return;
  }

  // Throttle style updates for perf.
  if (now - lastGlowTick >= 70) {
    const t = now / 1000;
    const apply = (n: any, color: string) => {
      const id = n.id();
      const phase = (hashString(id) % 1000) / 1000;
      const wave = 0.5 + 0.5 * Math.sin((t * 2.2 + phase) * Math.PI * 2);
      const blur = 6 + 14 * wave;
      const opacity = 0.15 + 0.55 * wave;
      n.style({
        'shadow-color': color,
        'shadow-offset-x': 0,
        'shadow-offset-y': 0,
        'shadow-blur': blur,
        'shadow-opacity': opacity
      });
    };
    running?.forEach((n) => apply(n, '#4fc3f7'));
    waiting?.forEach((n) => apply(n, '#d7ba7d'));
    lastGlowTick = now;
  }

  glowRaf = window.requestAnimationFrame(tickGlow);
}

function ensureGlowRunning(): void {
  const cy = renderer.getCy();
  if (!cy) return;
  const running = cy.nodes('.running');
  const waiting = cy.nodes('.waiting');
  if ((running && !running.empty()) || (waiting && !waiting.empty())) {
    if (glowRaf === null) glowRaf = window.requestAnimationFrame(tickGlow);
    return;
  }
  stopGlow();
}

let lastTapAt = 0;
let lastTapNodeId: string | null = null;

function focusNode(nodeId: string): void {
  const cy = renderer.getCy();
  if (!cy) return;
  const node = cy.getElementById(nodeId);
  if (!node || node.empty()) return;
  cy.animate({ center: { eles: node } }, { duration: 220 });
}

function truncate(text: string, max = 800): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + '…';
}

function formatValue(value: unknown): string {
  try {
    return truncate(JSON.stringify(value, null, 2));
  } catch {
    return truncate(String(value));
  }
}

function showTooltip(nodeId: string, runs: NodeExecution[], x: number, y: number): void {
  tooltipNodeId.value = nodeId;
  tooltipRuns.value = runs;
  tooltipVisible.value = true;
  tooltipX.value = x;
  tooltipY.value = y;
}

function hideTooltip(): void {
  tooltipVisible.value = false;
  tooltipNodeId.value = '';
  tooltipRuns.value = [];
}

function toElements(graph: GraphData): ElementDefinition[] {
  return buildGraphElements(graph);
}

const RUNTIME_LAYOUT_OPTS = {
  preferDirection: 'AUTO' as const,
  fitPadding: 30,
  dagreRankDir: 'TB' as const,
  dagreNodeSep: 40,
  dagreRankSep: 65
};

const RUNTIME_STYLE: Stylesheet[] = [
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
      'shadow-opacity': 0,
      'shadow-blur': 0,
      'shadow-color': '#4fc3f7',
      'shadow-offset-x': 0,
      'shadow-offset-y': 0,
      width: 'label',
      height: 'label',
      padding: '10px',
      shape: 'round-rectangle'
    }
  },
  // Match legacy Preview styles for internal control nodes.
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
    selector: 'node[type="TerminateNode"]',
    style: {
      shape: 'ellipse',
      'background-color': '#5c1e1e',
      'border-color': '#8b2d2d',
      width: '70px',
      height: '35px',
      'font-size': 11,
      padding: '5px'
    }
  },
  {
    selector: 'node.executed',
    style: {
      'border-color': '#2d9f4c',
      'background-color': '#1f2d23'
    }
  },
  {
    selector: 'node.error',
    style: {
      'border-color': '#f48771',
      'background-color': '#3a1e1e'
    }
  },
  {
    selector: 'node.running',
    style: {
      'border-color': '#4fc3f7',
      'background-color': '#0e639c',
      'border-width': 3
    }
  },
  {
    selector: 'node.waiting',
    style: {
      'border-color': '#d7ba7d',
      'border-width': 4
    }
  },
  {
    selector: 'node.selected',
    style: {
      'border-color': '#dcdcaa',
      'border-width': 4
    }
  },
  {
    selector: 'node.paused',
    style: {
      'border-color': '#d7ba7d',
      'border-width': 5
    }
  },
  {
    selector: 'node.debug-exception',
    style: {
      'border-color': '#f48771',
      'border-width': 6
    }
  },
  {
    selector: 'node.subgraph',
    style: {
      'background-opacity': 0.1,
      'background-color': '#0e639c',
      'border-style': 'dashed',
      'border-color': '#0e639c',
      'border-width': 2,
      'text-valign': 'top',
      'text-halign': 'center',
      'padding-top': '18px'
    }
  },
  {
    selector: 'edge',
    style: {
      width: 2,
      'line-color': '#7f7f7f',
      'target-arrow-color': '#7f7f7f',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      label: 'data(displayLabel)',
      color: '#9cdcfe',
      'font-size': 10,
      'text-rotation': 'none',
      'edge-text-rotation': 'none',
      'text-background-color': '#252526',
      'text-background-opacity': 0.9,
      'text-background-padding': '2px',
      'text-background-shape': 'roundrectangle',
      'text-wrap': 'wrap',
      'text-max-width': '160px'
    }
  }
];

function attachCyHandlers(core: Core): void {
  core.on('tap', (evt) => {
    if (evt.target === core) {
      emit('clearSelection');
    }
  });

  core.on('tap', 'node', (evt) => {
    const node = evt.target;
    const id = node.id();
    emit('selectNode', id);

    const now = Date.now();
    if (lastTapNodeId === id && now - lastTapAt < 280) {
      focusNode(id);
    }
    lastTapNodeId = id;
    lastTapAt = now;
  });

  // Hover tooltips for executed nodes.
  core.on('mouseover', 'node', (evt) => {
    const node = evt.target;
    const id = node.id();
    const runs = exec.value.nodeHistory?.[id];
    if (!runs || runs.length === 0) return;
    const rp = (evt as any).renderedPosition;
    if (!rp || typeof rp.x !== 'number' || typeof rp.y !== 'number') return;
    showTooltip(id, runs.slice().reverse().slice(0, 5), rp.x + 12, rp.y + 12);
  });
  core.on('mouseout', 'node', () => {
    hideTooltip();
  });
  core.on('mousemove', (_evt) => {
    if (!tooltipVisible.value) return;
    const evt = _evt as any;
    const rp = evt.renderedPosition;
    if (!rp || typeof rp.x !== 'number' || typeof rp.y !== 'number') return;
    tooltipX.value = rp.x + 12;
    tooltipY.value = rp.y + 12;
  });
  core.on('zoom pan', () => {
    hideTooltip();
  });
}

const renderer = new CyGraphRenderer({
  getContainer: () => containerRef.value,
  style: RUNTIME_STYLE,
  thresholdPx: 20,
  layout: (core) => applySmartDagreLayout(core, RUNTIME_LAYOUT_OPTS),
  onAfterInit: (core) => attachCyHandlers(core),
  onVisible: () => {
    hideTooltip();
    applyExecutionState();
  }
});

function applyExecutionState(): void {
  const cy = renderer.getCy();
  if (!cy) return;
  const runningSet = new Set(exec.value.runningNodes || []);
  const history = exec.value.nodeHistory || {};
  const selected = selectedNodeId.value;
  const pausedSet = new Set(pausedNodeIds.value || []);
  const exceptionSet = new Set(exceptionNodeIds.value || []);
  const waitingSet = new Set(waitingNodeIds.value || []);

  cy.batch(() => {
    cy.nodes().forEach((n) => {
      n.removeClass('running waiting executed error selected paused debug-exception');
      // Reset glow in case this node was previously running.
      n.style({ 'shadow-opacity': 0, 'shadow-blur': 0 });
      const id = n.id();
      const runs = history[id];
      if (runs && runs.length > 0) {
        const last = runs[runs.length - 1];
        if (last && last.status === 'error') n.addClass('error');
        else n.addClass('executed');
      }
      if (selected && id === selected) n.addClass('selected');
      if (pausedSet.has(id)) n.addClass('paused');
      if (exceptionSet.has(id)) n.addClass('debug-exception');
      if (waitingSet.has(id)) n.addClass('waiting');
    });
    for (const nodeId of runningSet) {
      const n = cy.getElementById(nodeId);
      if (n && !n.empty()) n.addClass('running');
    }
  });

  ensureGlowRunning();
}

function applyGraph(graph: GraphData | null): void {
  if (!graph) {
    renderer.destroy();
    lastGraphSig = null;
    stopGlow();
    hideTooltip();
    return;
  }

  const prevSig = lastGraphSig;
  const nextSig = graphSig(graph);
  const structureChanged = prevSig !== null && nextSig !== prevSig;
  lastGraphSig = nextSig;
  const elements = toElements(graph);
  const preserveViewport = prevSig !== null && !structureChanged;
  renderer.setElements(elements, { preserveViewport, preserveSelection: false, layout: true });
  applyExecutionState();
}

onMounted(() => {
  applyGraph(props.graph);
});

watch(
  () => props.graph,
  (g) => applyGraph(g),
  { deep: true }
);

watch(
  () => props.execution,
  () => applyExecutionState(),
  { deep: true }
);

watch(
  () => props.selectedNodeId,
  () => applyExecutionState()
);

watch(
  () => props.waitingNodeIds,
  () => applyExecutionState(),
  { deep: true }
);

watch(
  () => props.pausedNodeIds,
  () => applyExecutionState(),
  { deep: true }
);

watch(
  () => props.exceptionNodeIds,
  () => applyExecutionState(),
  { deep: true }
);

onBeforeUnmount(() => {
  renderer.destroy();
  stopGlow();
});
</script>

<template>
  <div class="root">
    <div ref="containerRef" class="canvas" />
    <div v-if="!hasGraph" class="placeholder">No graph data yet.</div>
    <div
      v-if="tooltipVisible"
      class="tooltip"
      :style="{ left: tooltipX + 'px', top: tooltipY + 'px' }"
    >
      <div class="tooltip-title">
        {{ tooltipNodeId }} · {{ tooltipRuns.length }} run(s)
      </div>
      <div class="tooltip-body">
        <div v-for="(r, idx) in tooltipRuns" :key="r.runId" class="run">
          <div class="run-title">
            #{{ tooltipRuns.length - idx }}
            <span class="mono"> {{ new Date(r.startedAt).toLocaleTimeString() }}</span>
            <span class="status" :class="r.status">{{ r.status }}</span>
          </div>
          <div v-if="r.inputs !== undefined" class="io">
            <div class="io-label">inputs</div>
            <pre class="io-json mono">{{ formatValue(r.inputs) }}</pre>
          </div>
          <div v-if="r.outputs !== undefined" class="io">
            <div class="io-label">outputs</div>
            <pre class="io-json mono">{{ formatValue(r.outputs) }}</pre>
          </div>
          <div v-if="r.error" class="io">
            <div class="io-label">error</div>
            <pre class="io-json mono">{{ r.error }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.root {
  position: relative;
  width: 100%;
  height: 100%;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  overflow: hidden;
}

.canvas {
  position: absolute;
  inset: 0;
}

.placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  opacity: 0.75;
  pointer-events: none;
}

.tooltip {
  position: absolute;
  z-index: 10;
  width: 360px;
  max-height: 360px;
  overflow: auto;
  border: 1px solid rgba(90, 90, 90, 0.8);
  background: rgba(30, 30, 30, 0.95);
  border-radius: 8px;
  padding: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  pointer-events: none;
}

.tooltip-title {
  font-weight: 700;
  font-size: 12px;
  margin-bottom: 8px;
  opacity: 0.95;
}

.tooltip-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.run {
  border-top: 1px solid rgba(90, 90, 90, 0.4);
  padding-top: 8px;
}

.run:first-child {
  border-top: none;
  padding-top: 0;
}

.run-title {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 12px;
  margin-bottom: 6px;
}

.status {
  margin-left: auto;
  text-transform: uppercase;
  font-size: 11px;
  opacity: 0.9;
}

.status.running {
  color: #4fc3f7;
}

.status.ok {
  color: #2d9f4c;
}

.status.error {
  color: #f48771;
}

.io {
  margin-bottom: 8px;
}

.io:last-child {
  margin-bottom: 0;
}

.io-label {
  font-size: 11px;
  opacity: 0.75;
  margin-bottom: 4px;
}

.io-json {
  margin: 0;
  font-size: 11px;
  line-height: 1.35;
  white-space: pre-wrap;
  word-break: break-word;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
}
</style>
