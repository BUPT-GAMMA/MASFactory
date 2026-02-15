<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRuntimeStore } from '../stores/runtime';
import { useUiStore } from '../stores/ui';
import { postMessage } from '../bridge/vscode';
import RuntimeGraphView from './RuntimeGraphView.vue';
import JsonTree from './JsonTree.vue';
import SessionBottomPane from './session/SessionBottomPane.vue';
import type { ExecutionState } from '../types/runtimeExec';

const props = defineProps<{
  sessionId: string;
  showBack?: boolean;
  showOpenInTab?: boolean;
  openInTabDisabled?: boolean;
  openInTabLabel?: string;
}>();

const emit = defineEmits<{
  (e: 'back'): void;
}>();

const runtime = useRuntimeStore();
const ui = useUiStore();

const activeSession = computed(
  () => runtime.sessions.find((s) => s.id === props.sessionId) || null
);
const archivedSession = computed(() => runtime.archivedSessions[props.sessionId] || null);
const session = computed(() => activeSession.value || archivedSession.value || null);
const isExited = computed(() => !!archivedSession.value && !activeSession.value);
const graph = computed(() => runtime.graphs[props.sessionId] || null);
const exec = computed<ExecutionState>(
  () => runtime.execution[props.sessionId] || { runningNodes: [], nodeHistory: {} }
);
const debugState = computed(() => runtime.debug[props.sessionId] || null);
const logs = computed(() =>
  runtime.logs.filter((l) => l.sessionId === props.sessionId).slice(-200).reverse()
);
const flows = computed(() =>
  runtime.flows.filter((f) => f.sessionId === props.sessionId).slice(-200).reverse()
);
const systemEvents = computed(() => {
  const sysLogs = runtime.systemLogs
    .filter((l) => l.sessionId === props.sessionId)
    .map((l) => ({ kind: 'log' as const, ts: l.ts, level: l.level, message: l.message }));
  const traces = runtime.traces
    .filter((t) => t.sessionId === props.sessionId)
    .map((t) => ({
      kind: 'trace' as const,
      ts: t.ts,
      dir: t.dir,
      messageType: t.messageType,
      payload: t.payload
    }));
  return [...sysLogs, ...traces].sort((a, b) => b.ts - a.ts).slice(0, 200);
});

const pausedNodeIds = computed(() => debugState.value?.pausedNodeIds || []);
const exceptionNodeIds = computed(() => debugState.value?.exceptionNodeIds || []);
const waitingNodeIds = computed(() => runtime.humanWaitingNodeIds(props.sessionId));
const humanPendingCount = computed(() => runtime.humanPendingCount(props.sessionId));
const humanChatCount = computed(() => runtime.humanChatForSession(props.sessionId).length);

function displayNode(id: string | null | undefined): string {
  if (!id) return '';
  const g = graph.value;
  const aliases = g?.nodeAliases?.[id];
  if (Array.isArray(aliases) && aliases.length > 0 && typeof aliases[0] === 'string' && aliases[0]) {
    return aliases[0];
  }
  const typ = g?.nodeTypes?.[id] ?? '';
  if (typ === 'entry' || id === 'entry' || id.endsWith('_entry')) return 'entry';
  if (typ === 'exit' || id === 'exit' || id.endsWith('_exit')) return 'exit';
  if (typ === 'Controller' || id.endsWith('_controller')) return 'controller';
  if (typ === 'TerminateNode' || id.endsWith('_terminate')) return 'terminate';
  return id;
}

const runningLabel = computed(() => {
  const nodes = exec.value.runningNodes || [];
  if (nodes.length === 0) return '—';
  const labels = nodes.map((n) => displayNode(n)).filter(Boolean);
  if (labels.length <= 3) return labels.join(', ');
  return `${labels.slice(0, 3).join(', ')} (+${labels.length - 3})`;
});

const selectedNodeId = ref<string | null>(null);

const splitRef = ref<HTMLDivElement | null>(null);
const isResizing = ref(false);
const bottomHeight = ref(240);
let splitResizeObserver: ResizeObserver | null = null;

type DragState = {
  startY: number;
  startBottomHeight: number;
  splitHeight: number;
  pointerId: number;
};
const drag = ref<DragState | null>(null);

const MIN_BOTTOM_HEIGHT = 160;
const MIN_GRAPH_HEIGHT = 220;
const HANDLE_HEIGHT = 6;

function clampBottomHeight(px: number, splitHeightPx: number): number {
  const maxBottom = Math.max(
    MIN_BOTTOM_HEIGHT,
    splitHeightPx - MIN_GRAPH_HEIGHT - HANDLE_HEIGHT
  );
  return Math.max(MIN_BOTTOM_HEIGHT, Math.min(maxBottom, px));
}

function loadBottomHeight(): void {
  try {
    const raw = window.localStorage.getItem('masfactoryVisualizer.sessionDetail.bottomHeightPx');
    if (!raw) return;
    const n = Number(raw);
    if (Number.isFinite(n) && n > 0) bottomHeight.value = n;
  } catch {
    // ignore
  }
}

function persistBottomHeight(): void {
  try {
    window.localStorage.setItem(
      'masfactoryVisualizer.sessionDetail.bottomHeightPx',
      String(Math.round(bottomHeight.value))
    );
  } catch {
    // ignore
  }
}

function onResizePointerDown(e: PointerEvent) {
  if (e.button !== 0) return;
  const split = splitRef.value;
  if (!split) return;
  const rect = split.getBoundingClientRect();
  const startBottom = clampBottomHeight(bottomHeight.value, rect.height);
  bottomHeight.value = startBottom;

  isResizing.value = true;
  drag.value = {
    startY: e.clientY,
    startBottomHeight: startBottom,
    splitHeight: rect.height,
    pointerId: e.pointerId
  };
  try {
    (e.currentTarget as HTMLElement | null)?.setPointerCapture(e.pointerId);
  } catch {
    // ignore
  }
  try {
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'row-resize';
  } catch {
    // ignore
  }
  e.preventDefault();
}

function onResizePointerMove(e: PointerEvent) {
  if (!isResizing.value || !drag.value) return;
  const delta = drag.value.startY - e.clientY;
  const next = drag.value.startBottomHeight + delta;
  bottomHeight.value = clampBottomHeight(next, drag.value.splitHeight);
}

function endResize() {
  if (!isResizing.value) return;
  isResizing.value = false;
  drag.value = null;
  persistBottomHeight();
  try {
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
  } catch {
    // ignore
  }
}

function onResizePointerUp(e: PointerEvent) {
  if (!isResizing.value) return;
  try {
    (e.currentTarget as HTMLElement | null)?.releasePointerCapture(e.pointerId);
  } catch {
    // ignore
  }
  endResize();
}

function onResizePointerCancel() {
  endResize();
}

function openInTab() {
  if (props.openInTabDisabled) return;
  runtime.openSessionInTab(props.sessionId);
}

function startStreaming() {
  streamingWanted.value = true;
  runtime.subscribe(props.sessionId);
}

function stopStreaming() {
  streamingWanted.value = false;
  runtime.unsubscribe(props.sessionId);
}

function onSelectNode(nodeId: string) {
  selectedNodeId.value = nodeId;
}

function clearSelection() {
  selectedNodeId.value = null;
}

const exceptionModalOpen = ref(false);
const lastExceptionTs = ref<number | null>(null);

function toggleChatPopup(): void {
  ui.toggleChat(props.sessionId);
}

const hasHumanChat = computed(() => humanChatCount.value > 0 || humanPendingCount.value > 0);

function openDebugLocation() {
  const loc = debugState.value?.location;
  if (!loc?.path) return;
  postMessage({
    type: 'openFileLocation',
    filePath: loc.path,
    line: loc.line,
    column: loc.column
  });
}

watch(
  () => [debugState.value?.paused, debugState.value?.reason, debugState.value?.ts] as const,
  ([paused, reason, ts]) => {
    if (!paused) {
      exceptionModalOpen.value = false;
      return;
    }
    if (String(reason || '').toLowerCase() !== 'exception') return;
    const n = typeof ts === 'number' && Number.isFinite(ts) ? ts : null;
    if (n && n !== lastExceptionTs.value) {
      lastExceptionTs.value = n;
      exceptionModalOpen.value = true;
    }
  }
);

watch(
  () => humanPendingCount.value,
  (next, prev) => {
    if ((prev ?? 0) === 0 && next > 0) {
      ui.openChat(props.sessionId);
    }
  }
);

watch(
  () => graph.value?.nodes,
  (nodes) => {
    const id = selectedNodeId.value;
    if (!id) return;
    if (!Array.isArray(nodes) || !nodes.includes(id)) {
      selectedNodeId.value = null;
    }
  }
);

onMounted(() => {
  loadBottomHeight();
  // Clamp to current container size (best-effort).
  window.requestAnimationFrame(() => {
    const split = splitRef.value;
    if (!split) return;
    const rect = split.getBoundingClientRect();
    bottomHeight.value = clampBottomHeight(bottomHeight.value, rect.height);
  });

  // Keep the persisted height sane when the panel is resized.
  try {
    splitResizeObserver = new ResizeObserver((entries) => {
      if (isResizing.value) return;
      const el = entries[0]?.target as HTMLElement | undefined;
      if (!el) return;
      const h = el.getBoundingClientRect().height;
      bottomHeight.value = clampBottomHeight(bottomHeight.value, h);
    });
    if (splitRef.value) splitResizeObserver.observe(splitRef.value);
  } catch {
    // ignore
  }

  // Auto-start streaming when the user is viewing a live session.
  ensureStreaming();
});

onBeforeUnmount(() => {
  // Best-effort: stop streaming for this view.
  try {
    runtime.unsubscribe(props.sessionId);
  } catch {
    // ignore
  }
  try {
    splitResizeObserver?.disconnect();
  } catch {
    // ignore
  }
  splitResizeObserver = null;
});

const streamingWanted = ref(true);

function ensureStreaming() {
  if (!streamingWanted.value) return;
  const s = activeSession.value;
  if (!s) return;
  if (s.subscribed) return;
  runtime.subscribe(props.sessionId);
}

watch(
  () => props.sessionId,
  () => {
    // New session selected: default to streaming.
    streamingWanted.value = true;
    selectedNodeId.value = null;
    ensureStreaming();
  }
);

watch(
  () => activeSession.value?.subscribed,
  () => ensureStreaming()
);
</script>

<template>
  <div class="root">
    <div class="header">
      <div class="title-row">
        <button v-if="showBack" class="btn secondary" @click="emit('back')">Back</button>
        <div class="title">
          <span class="name">{{ session?.graphName ?? '(unknown graph)' }}</span>
          <span class="meta mono">· {{ sessionId }}</span>
          <span v-if="isExited" class="meta exited">Process exited</span>
        </div>
      </div>

      <div class="actions">
        <button
          v-if="hasHumanChat"
          class="btn secondary"
          title="Show/Hide Human chat window"
          @click="toggleChatPopup"
        >
          Chat
          <span v-if="humanPendingCount > 0" class="chat-badge">{{ humanPendingCount }}</span>
        </button>
        <button
          v-if="showOpenInTab !== false"
          class="btn secondary"
          title="Open this session in a dedicated tab"
          @click="openInTab"
          :disabled="openInTabDisabled"
        >
          {{ openInTabLabel ?? 'Open in Tab' }}
        </button>
        <button
          v-if="activeSession && !activeSession.subscribed"
          class="btn"
          title="Start streaming data from this process"
          @click="startStreaming"
        >
          Start
        </button>
        <button
          v-else-if="activeSession && activeSession.subscribed"
          class="btn secondary"
          title="Stop streaming data from this process"
          @click="stopStreaming"
        >
          Stop
        </button>
      </div>
    </div>

    <div v-if="isExited" class="exit-banner">
      <div class="exit-title">Process exited</div>
      <div class="exit-sub mono">
        {{ archivedSession?.endedAt ? new Date(archivedSession.endedAt).toLocaleTimeString() : '' }}
      </div>
    </div>

    <div v-if="debugState?.paused" class="debug-banner">
      <div class="debug-title">
        <span class="badge">PAUSED</span>
        <span class="reason mono">{{ debugState.reason }}</span>
        <span v-if="debugState.description" class="desc">{{ debugState.description }}</span>
      </div>
      <div class="debug-meta">
        <span v-if="debugState.location?.path" class="mono">
          {{ debugState.location.path }}<span v-if="debugState.location.line">:{{ debugState.location.line }}</span>
        </span>
        <span v-else class="dim">No location info.</span>
        <span v-if="pausedNodeIds.length > 0" class="mono dim">· node: {{ pausedNodeIds.join(', ') }}</span>
      </div>
      <div class="debug-actions">
        <button class="btn secondary small" :disabled="!debugState.location?.path" @click="openDebugLocation">
          Open Location
        </button>
        <button
          v-if="String(debugState.reason || '').toLowerCase() === 'exception'"
          class="btn secondary small"
          @click="exceptionModalOpen = true"
        >
          View Exception
        </button>
      </div>
    </div>

    <div class="info">
      <div class="kv">
        <div class="k">Mode</div>
        <div class="v">{{ session?.mode ?? '—' }}</div>
      </div>
      <div class="kv">
        <div class="k">PID</div>
        <div class="v">{{ session?.pid ?? '—' }}</div>
      </div>
      <div class="kv">
        <div class="k">Last Seen</div>
        <div class="v">
          {{ session?.lastSeenAt ? new Date(session.lastSeenAt).toLocaleTimeString() : '—' }}
        </div>
      </div>
      <div class="kv">
        <div class="k">Nodes</div>
        <div class="v">{{ graph?.nodes?.length ?? '—' }}</div>
      </div>
      <div class="kv">
        <div class="k">Edges</div>
        <div class="v">{{ graph?.edges?.length ?? '—' }}</div>
      </div>
      <div class="kv">
        <div class="k">Running</div>
        <div class="v mono">{{ runningLabel }}</div>
      </div>
    </div>

    <div ref="splitRef" class="split" :class="{ resizing: isResizing }">
      <div class="graph">
        <RuntimeGraphView
          :graph="graph"
          :execution="exec"
          :selected-node-id="selectedNodeId"
          :paused-node-ids="pausedNodeIds"
          :exception-node-ids="exceptionNodeIds"
          :waiting-node-ids="waitingNodeIds"
          @select-node="onSelectNode"
          @clear-selection="clearSelection"
        />
      </div>

      <div
        class="resize-handle"
        title="Drag to resize"
        @pointerdown="onResizePointerDown"
        @pointermove="onResizePointerMove"
        @pointerup="onResizePointerUp"
        @pointercancel="onResizePointerCancel"
      >
        <div class="resize-grip" />
      </div>

      <div class="bottom" :style="{ height: bottomHeight + 'px' }">
        <SessionBottomPane
          :session-id="props.sessionId"
          :graph="graph"
          :exec="exec"
          :debug-state="debugState"
          :logs="logs"
          :flows="flows"
          :system-events="systemEvents"
          :selected-node-id="selectedNodeId"
          :human-pending-count="humanPendingCount"
          :display-node="displayNode"
          @clear-selection="clearSelection"
        />
      </div>
    </div>

    <div v-if="exceptionModalOpen" class="modal-backdrop" @click.self="exceptionModalOpen = false">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">Exception</div>
          <button class="btn secondary small" @click="exceptionModalOpen = false">Close</button>
        </div>
        <div class="modal-body">
          <div class="modal-kv">
            <div class="k">Reason</div>
            <div class="v mono">{{ debugState?.reason ?? '—' }}</div>
          </div>
          <div v-if="debugState?.exception?.id" class="modal-kv">
            <div class="k">Exception ID</div>
            <div class="v mono">{{ debugState.exception.id }}</div>
          </div>
          <div v-if="debugState?.exception?.description" class="modal-kv">
            <div class="k">Description</div>
            <div class="v">{{ debugState.exception.description }}</div>
          </div>
          <div v-if="debugState?.location?.path" class="modal-kv">
            <div class="k">Location</div>
            <div class="v mono">
              {{ debugState.location.path }}<span v-if="debugState.location.line">:{{ debugState.location.line }}</span>
            </div>
          </div>
          <div v-if="debugState?.exception?.details !== undefined" class="modal-kv block">
            <div class="k">Details</div>
            <div class="v">
              <JsonTree :value="debugState?.exception?.details" :open="true" :dense="true" />
            </div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.root {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  box-sizing: border-box;
}

.header {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.title {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.name {
  font-weight: 700;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.meta {
  opacity: 0.8;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.meta.exited {
  opacity: 0.95;
  color: #f48771;
  border: 1px solid rgba(244, 135, 113, 0.35);
  background: rgba(244, 135, 113, 0.12);
  padding: 2px 6px;
  border-radius: 999px;
  font-size: 11px;
  flex-shrink: 0;
}

.actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}

.btn {
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--vscode-button-border, transparent);
  background: var(--vscode-button-background, #0e639c);
  color: var(--vscode-button-foreground, #fff);
  cursor: pointer;
}

.btn:hover {
  background: var(--vscode-button-hoverBackground, #1177bb);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn:disabled:hover {
  background: var(--vscode-button-background, #0e639c);
}

.btn.secondary {
  background: transparent;
  color: var(--vscode-editor-foreground);
  border-color: var(--vscode-panel-border, #2d2d2d);
}

.btn.secondary:hover {
  background: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.06));
}

.chat-badge {
  margin-left: 6px;
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid rgba(215, 186, 125, 0.55);
  background: rgba(215, 186, 125, 0.16);
}

.flow {
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  overflow: hidden;
}

.flow > summary {
  list-style: none;
  cursor: pointer;
}

.flow > summary::-webkit-details-marker {
  display: none;
}

.flow-body {
  border-top: 1px solid var(--vscode-panel-border, #2d2d2d);
  padding: 8px 10px;
}

.info {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  padding: 10px;
}

.exit-banner {
  border: 1px solid rgba(244, 135, 113, 0.45);
  background: rgba(244, 135, 113, 0.08);
  border-radius: 8px;
  padding: 10px;
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: baseline;
}

.exit-title {
  font-size: 12px;
  font-weight: 700;
  color: #f48771;
}

.exit-sub {
  font-size: 12px;
  opacity: 0.9;
}

.debug-banner {
  border: 1px solid rgba(215, 186, 125, 0.55);
  background: rgba(215, 186, 125, 0.08);
  border-radius: 8px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.debug-title {
  display: flex;
  gap: 10px;
  align-items: baseline;
  min-width: 0;
}

.badge {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 999px;
  background: rgba(215, 186, 125, 0.25);
  border: 1px solid rgba(215, 186, 125, 0.35);
  flex-shrink: 0;
}

.reason {
  font-size: 12px;
  opacity: 0.9;
}

.desc {
  font-size: 12px;
  opacity: 0.85;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.debug-meta {
  font-size: 12px;
  opacity: 0.9;
  display: flex;
  gap: 8px;
  align-items: baseline;
  min-width: 0;
}

.debug-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.dim {
  opacity: 0.7;
}

.kv {
  display: flex;
  gap: 8px;
  align-items: baseline;
}

.k {
  font-size: 12px;
  opacity: 0.75;
}

.v {
  font-size: 12px;
}

.graph {
  flex: 1;
  min-height: 220px;
  min-width: 0;
  position: relative;
}

.split {
  flex: 1;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.resize-handle {
  height: 6px;
  flex-shrink: 0;
  cursor: row-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  margin: 2px 0;
  background: transparent;
  user-select: none;
  touch-action: none;
}

.resize-handle:hover,
.split.resizing .resize-handle {
  background: rgba(14, 99, 156, 0.14);
}

.resize-grip {
  width: 42px;
  height: 2px;
  border-radius: 999px;
  background: rgba(180, 180, 180, 0.35);
}

.bottom {
  min-height: 160px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.btn.small {
  padding: 4px 8px;
  font-size: 11px;
}

.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  width: min(820px, 92vw);
  max-height: 82vh;
  overflow: auto;
  background: var(--vscode-editor-background);
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 10px;
  padding: 12px;
  box-sizing: border-box;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.modal-title {
  font-size: 13px;
  font-weight: 700;
}

.modal-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.modal-kv {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 10px;
  align-items: baseline;
}

.modal-kv.block {
  grid-template-columns: 120px 1fr;
  align-items: start;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
}
</style>
