<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import type { ExecutionState } from '../../types/runtimeExec';
import HumanChatPanel from '../HumanChatPanel.vue';
import JsonTree from '../JsonTree.vue';
import NodeDetail from '../NodeDetail.vue';

type BottomTabId = 'node' | 'logs' | 'messages' | 'human' | 'system' | 'graph';

const props = defineProps<{
  sessionId: string;
  graph: any;
  exec: ExecutionState;
  debugState: any;
  logs: any[];
  flows: any[];
  systemEvents: any[];
  selectedNodeId: string | null;
  humanPendingCount: number;
  displayNode: (id: string | null | undefined) => string;
}>();

const emit = defineEmits<{
  (e: 'clearSelection'): void;
}>();

const activeTab = ref<BottomTabId>('logs');

watch(
  () => props.selectedNodeId,
  (next) => {
    if (next) activeTab.value = 'node';
  }
);

const graphJson = computed(() => (props.graph ? JSON.stringify(props.graph, null, 2) : '—'));

type MessageRow = {
  key: string;
  ts: number;
  sender: string;
  receiver: string;
  via: 'edge' | 'attr';
  field: string;
  content: unknown;
  flow: unknown;
  rowspan: number;
  isFirst: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function isExpandableValue(value: unknown): boolean {
  return isRecord(value) || Array.isArray(value);
}

function formatScalar(value: unknown): string {
  if (value === undefined) return '—';
  if (value === null) return 'null';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

const messageRows = computed<MessageRow[]>(() => {
  const rows: MessageRow[] = [];

  for (let idx = 0; idx < props.flows.length; idx++) {
    const f = props.flows[idx];
    const kind = String((f as any)?.kind || '');
    const baseKey = `${(f as any)?.ts}:${idx}:${kind}`;

    const via: 'edge' | 'attr' = kind === 'EDGE_SEND' ? 'edge' : 'attr';
    const sender = kind === 'EDGE_SEND' ? props.displayNode((f as any)?.from) : props.displayNode((f as any)?.node);
    const receiver = kind === 'EDGE_SEND' ? props.displayNode((f as any)?.to) : String((f as any)?.scope || 'attributes');

    const fieldRows: Array<{ field: string; content: unknown }> = [];

    if (kind === 'EDGE_SEND') {
      const message = isRecord((f as any)?.message) ? ((f as any).message as Record<string, unknown>) : {};
      const keys = Array.isArray((f as any)?.keys) && (f as any).keys.length > 0 ? (f as any).keys : Object.keys(message);
      for (const k of keys) {
        fieldRows.push({ field: String(k), content: message[String(k)] });
      }
    } else if (kind === 'ATTR_PULL') {
      const values = isRecord((f as any)?.values) ? ((f as any).values as Record<string, unknown>) : {};
      const keys = Array.isArray((f as any)?.keys) && (f as any).keys.length > 0 ? (f as any).keys : Object.keys(values);
      for (const k of keys) {
        const key = String(k);
        fieldRows.push({ field: key, content: key in values ? values[key] : '<missing>' });
      }
    } else if (kind === 'ATTR_PUSH') {
      const changes = isRecord((f as any)?.changes) ? ((f as any).changes as Record<string, unknown>) : {};
      const keys = Object.keys(changes);
      for (const k of keys) {
        fieldRows.push({ field: k, content: changes[k] });
      }
    } else {
      fieldRows.push({ field: '—', content: f });
    }

    if (fieldRows.length === 0) continue;

    const rowspan = fieldRows.length;
    for (let j = 0; j < fieldRows.length; j++) {
      rows.push({
        key: `${baseKey}:${j}:${fieldRows[j].field}`,
        ts: typeof (f as any)?.ts === 'number' ? (f as any).ts : Date.now(),
        sender,
        receiver,
        via,
        field: fieldRows[j].field,
        content: fieldRows[j].content,
        flow: f,
        rowspan,
        isFirst: j === 0
      });
    }
  }

  return rows;
});

const msgFieldColWidthPx = ref(220);
const msgResizing = ref(false);
let msgResizePointerId: number | null = null;
let msgResizeStartX = 0;
let msgResizeStartWidth = 220;

const MSG_FIELD_MIN = 120;
const MSG_FIELD_MAX = 520;

function loadMsgColumnWidth(): void {
  try {
    const raw = window.localStorage.getItem('masfactoryVisualizer.messages.fieldColWidthPx');
    if (!raw) return;
    const n = Number(raw);
    if (Number.isFinite(n) && n > 0) {
      msgFieldColWidthPx.value = Math.max(MSG_FIELD_MIN, Math.min(MSG_FIELD_MAX, Math.round(n)));
    }
  } catch {
    // ignore
  }
}

function persistMsgColumnWidth(): void {
  try {
    window.localStorage.setItem('masfactoryVisualizer.messages.fieldColWidthPx', String(Math.round(msgFieldColWidthPx.value)));
  } catch {
    // ignore
  }
}

function onMsgResizeDown(e: PointerEvent) {
  if (e.button !== 0) return;
  msgResizing.value = true;
  msgResizePointerId = e.pointerId;
  msgResizeStartX = e.clientX;
  msgResizeStartWidth = msgFieldColWidthPx.value;
  try {
    (e.currentTarget as HTMLElement | null)?.setPointerCapture(e.pointerId);
  } catch {
    // ignore
  }
  try {
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  } catch {
    // ignore
  }
  e.preventDefault();
}

function onMsgResizeMove(e: PointerEvent) {
  if (!msgResizing.value) return;
  if (msgResizePointerId !== null && e.pointerId !== msgResizePointerId) return;
  const dx = e.clientX - msgResizeStartX;
  const next = msgResizeStartWidth + dx;
  msgFieldColWidthPx.value = Math.max(MSG_FIELD_MIN, Math.min(MSG_FIELD_MAX, Math.round(next)));
}

function endMsgResize(e?: PointerEvent) {
  if (!msgResizing.value) return;
  msgResizing.value = false;
  msgResizePointerId = null;
  persistMsgColumnWidth();
  try {
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  } catch {
    // ignore
  }
  if (e) {
    try {
      (e.currentTarget as HTMLElement | null)?.releasePointerCapture(e.pointerId);
    } catch {
      // ignore
    }
  }
}

const messageDetailOpen = ref(false);
const messageDetailFlow = ref<unknown>(null);

function compactUndefined(value: unknown): unknown {
  if (value === undefined) return undefined;
  if (Array.isArray(value)) {
    const next = value.map((v) => compactUndefined(v)).filter((v) => v !== undefined);
    return next;
  }
  if (isRecord(value)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      if (v === undefined) continue;
      const next = compactUndefined(v);
      if (next === undefined) continue;
      out[k] = next;
    }
    return out;
  }
  return value;
}

function buildFlowDetail(flow: unknown): unknown {
  if (!isRecord(flow)) return flow;

  const kind = String((flow as any).kind || 'FLOW');
  const tsRaw = (flow as any).ts;
  const ts = typeof tsRaw === 'number' && Number.isFinite(tsRaw) ? tsRaw : Date.now();
  const base: Record<string, unknown> = {
    kind,
    ts,
    time: new Date(ts).toLocaleTimeString()
  };

  if (kind === 'EDGE_SEND') {
    const from = typeof (flow as any).from === 'string' ? ((flow as any).from as string) : '';
    const to = typeof (flow as any).to === 'string' ? ((flow as any).to as string) : '';
    const rawMessage = (flow as any).message;
    const message = isRecord(rawMessage) ? (rawMessage as Record<string, unknown>) : rawMessage;
    const rawKeys = (flow as any).keys;
    const keys =
      Array.isArray(rawKeys) && rawKeys.length > 0
        ? rawKeys.map((k) => String(k))
        : isRecord(message)
          ? Object.keys(message as any)
          : [];
    const fields = keys.map((k) => ({
      field: k,
      content: isRecord(message) ? ((message as any)[k] ?? '<missing>') : undefined
    }));
    return compactUndefined({
      ...base,
      via: 'edge',
      sender: props.displayNode(from),
      receiver: props.displayNode(to),
      from,
      to,
      keys: keys.length > 0 ? keys : undefined,
      keysDetails: isRecord((flow as any).keysDetails) ? (flow as any).keysDetails : undefined,
      message,
      fields,
      truncated: (flow as any).truncated
    });
  }

  if (kind === 'ATTR_PULL') {
    const node = typeof (flow as any).node === 'string' ? ((flow as any).node as string) : '';
    const scope = typeof (flow as any).scope === 'string' && (flow as any).scope ? String((flow as any).scope) : 'attributes';
    const rawValues = (flow as any).values;
    const values = isRecord(rawValues) ? (rawValues as Record<string, unknown>) : rawValues;
    const rawKeys = (flow as any).keys;
    const keys =
      Array.isArray(rawKeys) && rawKeys.length > 0
        ? rawKeys.map((k) => String(k))
        : isRecord(values)
          ? Object.keys(values as any)
          : [];
    const fields = keys.map((k) => ({
      field: k,
      content: isRecord(values) ? ((values as any)[k] ?? '<missing>') : undefined
    }));
    return compactUndefined({
      ...base,
      via: 'attr',
      sender: props.displayNode(node),
      receiver: scope,
      node,
      scope,
      keys: keys.length > 0 ? keys : undefined,
      totalKeys: typeof (flow as any).totalKeys === 'number' ? (flow as any).totalKeys : undefined,
      truncated: (flow as any).truncated,
      values,
      fields
    });
  }

  if (kind === 'ATTR_PUSH') {
    const node = typeof (flow as any).node === 'string' ? ((flow as any).node as string) : '';
    const scope = typeof (flow as any).scope === 'string' && (flow as any).scope ? String((flow as any).scope) : 'attributes';
    const rawChanges = (flow as any).changes;
    const changes = isRecord(rawChanges) ? (rawChanges as Record<string, unknown>) : rawChanges;
    const keys = isRecord(changes) ? Object.keys(changes as any) : [];
    const fields = keys.map((k) => ({
      field: k,
      content: isRecord(changes) ? (changes as any)[k] : undefined
    }));
    return compactUndefined({
      ...base,
      via: 'attr',
      sender: props.displayNode(node),
      receiver: scope,
      node,
      scope,
      keys: keys.length > 0 ? keys : undefined,
      totalKeys: typeof (flow as any).totalKeys === 'number' ? (flow as any).totalKeys : undefined,
      truncated: (flow as any).truncated,
      changes,
      fields
    });
  }

  return compactUndefined(flow);
}

function openMessageDetail(flow: unknown) {
  messageDetailFlow.value = buildFlowDetail(flow);
  messageDetailOpen.value = true;
}

onMounted(() => {
  loadMsgColumnWidth();
});
</script>

<template>
  <div class="root">
    <div class="tabs">
      <button class="tab" :class="{ active: activeTab === 'node' }" @click="activeTab = 'node'">
        Node
        <span v-if="selectedNodeId" class="tab-hint mono">· {{ displayNode(selectedNodeId) }}</span>
      </button>
      <button class="tab" :class="{ active: activeTab === 'logs' }" @click="activeTab = 'logs'">Logs</button>
      <button class="tab" :class="{ active: activeTab === 'messages' }" @click="activeTab = 'messages'">Messages</button>
      <button class="tab" :class="{ active: activeTab === 'human' }" @click="activeTab = 'human'">
        Human
        <span v-if="humanPendingCount > 0" class="tab-badge">{{ humanPendingCount }}</span>
      </button>
      <button class="tab" :class="{ active: activeTab === 'system' }" @click="activeTab = 'system'">System</button>
      <button class="tab" :class="{ active: activeTab === 'graph' }" @click="activeTab = 'graph'">Graph Structure</button>
    </div>

    <div class="body">
      <div v-if="activeTab === 'node'" class="node-detail">
        <div v-if="!selectedNodeId" class="empty">Click a node in the graph to view details.</div>
        <div v-else class="node-detail-body">
          <div class="node-detail-actions">
            <button class="btn secondary small" @click="emit('clearSelection')">Clear</button>
          </div>
          <NodeDetail :node-id="selectedNodeId" :graph="graph" :exec="exec" :debug="debugState" />
        </div>
      </div>

      <div v-else-if="activeTab === 'logs'" class="list">
        <div v-if="logs.length === 0" class="empty">No logs yet.</div>
        <div v-else class="row log header">
          <span class="ts mono">Time</span>
          <span class="lvl mono">Level</span>
          <span class="msg mono">Message</span>
        </div>
        <div v-for="l in logs" :key="l.ts + ':' + (l.message || '')" class="row log">
          <span class="ts mono">{{ new Date(l.ts).toLocaleTimeString() }}</span>
          <span class="lvl" :class="l.level">{{ l.level }}</span>
          <span class="msg">{{ l.message }}</span>
        </div>
      </div>

      <div v-else-if="activeTab === 'messages'" class="messages">
        <div v-if="messageRows.length === 0" class="empty">No messages yet.</div>
        <table v-else class="msg-table">
          <colgroup>
            <col style="width: 90px" />
            <col style="width: 170px" />
            <col style="width: 170px" />
            <col style="width: 70px" />
            <col :style="{ width: msgFieldColWidthPx + 'px' }" />
            <col />
            <col style="width: 92px" />
          </colgroup>
          <thead>
            <tr>
              <th class="mono">Time</th>
              <th class="mono">Sender</th>
              <th class="mono">Receiver</th>
              <th class="mono">Via</th>
              <th class="mono field-head">
                Field
                <div
                  class="col-resizer"
                  title="Drag to resize Field/Content"
                  @pointerdown="onMsgResizeDown"
                  @pointermove="onMsgResizeMove"
                  @pointerup="endMsgResize"
                  @pointercancel="endMsgResize"
                />
              </th>
              <th class="mono">Content</th>
              <th class="mono">Detail</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in messageRows" :key="r.key">
              <td v-if="r.isFirst" :rowspan="r.rowspan" class="mono ts-cell">
                {{ new Date(r.ts).toLocaleTimeString() }}
              </td>
              <td v-if="r.isFirst" :rowspan="r.rowspan" class="mono sender-cell">
                {{ r.sender }}
              </td>
              <td v-if="r.isFirst" :rowspan="r.rowspan" class="mono receiver-cell">
                {{ r.receiver }}
              </td>
              <td v-if="r.isFirst" :rowspan="r.rowspan" class="mono via-cell">
                {{ r.via }}
              </td>
              <td class="mono field-cell">{{ r.field }}</td>
              <td class="content-cell">
                <JsonTree v-if="isExpandableValue(r.content)" :value="r.content" :open="false" :dense="true" />
                <pre v-else class="content-text mono">{{ formatScalar(r.content) }}</pre>
              </td>
              <td v-if="r.isFirst" :rowspan="r.rowspan" class="action-cell">
                <button class="btn secondary small" @click="openMessageDetail(r.flow)">View</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-else-if="activeTab === 'human'" class="human">
        <HumanChatPanel :session-id="sessionId" />
      </div>

      <div v-else-if="activeTab === 'system'" class="list">
        <div v-if="systemEvents.length === 0" class="empty">No system events yet.</div>
        <div v-else class="row system header">
          <span class="ts mono">Time</span>
          <span class="dir mono">Dir/Level</span>
          <span class="typ mono">Type</span>
          <span class="msg mono">Message</span>
        </div>
        <div
          v-for="e in systemEvents"
          :key="e.ts + ':' + e.kind + ':' + (e.kind === 'trace' ? e.messageType : e.message)"
          class="row system"
        >
          <span class="ts mono">{{ new Date(e.ts).toLocaleTimeString() }}</span>
          <template v-if="e.kind === 'log'">
            <span class="lvl" :class="e.level">{{ e.level }}</span>
            <span class="typ mono">LOG</span>
            <span class="msg">{{ e.message }}</span>
          </template>
          <template v-else>
            <span class="dir mono" :class="e.dir">{{ e.dir.toUpperCase() }}</span>
            <span class="typ mono">{{ e.messageType }}</span>
            <span class="msg mono">{{ e.payload ? JSON.stringify(e.payload) : '' }}</span>
          </template>
        </div>
      </div>

      <pre v-else class="json mono">{{ graphJson }}</pre>
    </div>

    <div
      v-if="messageDetailOpen"
      class="modal-backdrop"
      @click.self="
        messageDetailOpen = false;
        messageDetailFlow = null;
      "
    >
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">Message Detail</div>
          <button
            class="btn secondary small"
            @click="
              messageDetailOpen = false;
              messageDetailFlow = null;
            "
          >
            Close
          </button>
        </div>
        <div class="modal-body">
          <JsonTree :value="messageDetailFlow" :open="true" :dense="false" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.root {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.tabs {
  display: flex;
  gap: 6px;
  padding: 8px;
  border-bottom: 1px solid var(--vscode-panel-border, #2d2d2d);
  background: var(--vscode-editor-background);
}

.tab {
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--vscode-editor-foreground);
  cursor: pointer;
}

.tab:hover {
  background: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.06));
}

.tab.active {
  background: rgba(14, 99, 156, 0.18);
  border-color: rgba(14, 99, 156, 0.45);
}

.tab-hint {
  margin-left: 6px;
  opacity: 0.75;
  font-size: 11px;
}

.tab-badge {
  margin-left: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  background: rgba(215, 186, 125, 0.18);
  border: 1px solid rgba(215, 186, 125, 0.45);
  color: var(--vscode-editor-foreground);
}

.body {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.human {
  height: 100%;
  min-height: 0;
  padding: 10px;
  box-sizing: border-box;
}

.node-detail {
  padding: 10px;
}

.node-detail-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
}

.row {
  display: grid;
  grid-template-columns: 90px 70px 130px 1fr;
  gap: 10px;
  align-items: baseline;
  font-size: 12px;
  line-height: 1.4;
}

.row.log {
  grid-template-columns: 90px 70px 1fr;
  align-items: start;
}

.row.system {
  align-items: start;
}

.row.log .msg,
.row.system .msg {
  max-height: 180px;
  overflow: auto;
}

.row.header {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--vscode-editor-background);
  padding: 6px 8px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
}

.ts {
  opacity: 0.75;
}

.lvl {
  text-transform: uppercase;
  opacity: 0.85;
}

.lvl.warn {
  color: #d7ba7d;
}

.lvl.error {
  color: #f48771;
}

.dir {
  opacity: 0.85;
}

.dir.in {
  color: #9cdcfe;
}

.dir.out {
  color: #b5cea8;
}

.typ {
  opacity: 0.9;
}

.msg {
  min-width: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.messages {
  padding: 10px;
}

.msg-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  table-layout: fixed;
}

.msg-table th,
.msg-table td {
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  padding: 6px 8px;
  vertical-align: top;
}

.msg-table thead th {
  background: rgba(14, 99, 156, 0.08);
  position: sticky;
  top: 0;
  z-index: 1;
}

.field-head {
  position: relative;
  user-select: none;
}

.col-resizer {
  position: absolute;
  right: -3px;
  top: 0;
  width: 6px;
  height: 100%;
  cursor: col-resize;
  touch-action: none;
}

.col-resizer:hover {
  background: rgba(14, 99, 156, 0.18);
}

.ts-cell {
  opacity: 0.85;
  white-space: nowrap;
}

.via-cell {
  text-transform: uppercase;
  opacity: 0.85;
  white-space: nowrap;
}

.field-cell {
  white-space: nowrap;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.content-cell {
  min-width: 0;
}

.content-text {
  margin: 0;
  font-size: 12px;
  line-height: 1.4;
  white-space: pre-wrap;
  max-height: 180px;
  overflow: auto;
}

.action-cell {
  text-align: right;
  vertical-align: top;
}

.empty {
  padding: 10px;
  opacity: 0.8;
}

.json {
  margin: 0;
  padding: 10px;
  font-size: 12px;
  line-height: 1.4;
  white-space: pre;
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

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
    monospace;
}
</style>
