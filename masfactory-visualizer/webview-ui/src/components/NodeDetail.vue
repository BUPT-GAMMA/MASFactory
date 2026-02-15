<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { postMessage } from '../bridge/vscode';
import type { GraphData } from '../types/graph';
import type { ExecutionState, NodeExecution } from '../types/runtimeExec';
import type { DebugSessionState } from '../stores/runtime';
import JsonTree from './JsonTree.vue';

const props = defineProps<{
  nodeId: string;
  graph: GraphData | null;
  exec: ExecutionState;
  debug?: DebugSessionState | null;
}>();

type TokenUsage = { total?: number; prompt?: number; completion?: number } | number;

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function extractTokenUsage(value: unknown): TokenUsage | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const v: any = value as any;

  const tokenUsageObj = v?.token_usage ?? v?.tokenUsage;
  if (tokenUsageObj && typeof tokenUsageObj === 'object' && !Array.isArray(tokenUsageObj)) {
    const total = asNumber(tokenUsageObj.total_tokens ?? tokenUsageObj.totalTokens ?? tokenUsageObj.total);
    const prompt = asNumber(tokenUsageObj.prompt_tokens ?? tokenUsageObj.promptTokens ?? tokenUsageObj.prompt);
    const completion = asNumber(
      tokenUsageObj.completion_tokens ?? tokenUsageObj.completionTokens ?? tokenUsageObj.completion
    );
    if (total !== null || prompt !== null || completion !== null) {
      const out: { total?: number; prompt?: number; completion?: number } = {};
      if (total !== null) out.total = total;
      if (prompt !== null) out.prompt = prompt;
      if (completion !== null) out.completion = completion;
      return out;
    }
  }

  const directKeys = ['token_usage', 'tokenUsage', 'tokens', 'total_tokens', 'totalTokens'];
  for (const k of directKeys) {
    const n = asNumber(v?.[k]);
    if (n !== null) return n;
  }

  const usage = v?.usage;
  if (usage && typeof usage === 'object' && !Array.isArray(usage)) {
    const total = asNumber(usage.total_tokens ?? usage.totalTokens);
    const prompt = asNumber(usage.prompt_tokens ?? usage.promptTokens);
    const completion = asNumber(usage.completion_tokens ?? usage.completionTokens);
    if (total !== null || prompt !== null || completion !== null) {
      const out: { total?: number; prompt?: number; completion?: number } = {};
      if (total !== null) out.total = total;
      if (prompt !== null) out.prompt = prompt;
      if (completion !== null) out.completion = completion;
      return out;
    }
  }

  const metrics = v?.metrics;
  if (metrics && typeof metrics === 'object' && !Array.isArray(metrics)) {
    const nested = extractTokenUsage(metrics);
    if (nested) return nested;
  }

  return null;
}

function formatDurationMs(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  return `${(ms / 60_000).toFixed(2)} min`;
}

function formatTokenUsage(usage: TokenUsage | null): string {
  if (!usage) return '—';
  if (typeof usage === 'number') return String(Math.round(usage));
  const total = usage.total ?? null;
  const prompt = usage.prompt ?? null;
  const completion = usage.completion ?? null;
  if (total !== null && prompt !== null && completion !== null) {
    return `${Math.round(total)} (p=${Math.round(prompt)}, c=${Math.round(completion)})`;
  }
  if (total !== null) return String(Math.round(total));
  if (prompt !== null || completion !== null) {
    const p = prompt !== null ? `p=${Math.round(prompt)}` : '';
    const c = completion !== null ? `c=${Math.round(completion)}` : '';
    return [p, c].filter(Boolean).join(', ') || '—';
  }
  return '—';
}

const nodeType = computed(() => props.graph?.nodeTypes?.[props.nodeId] ?? 'Node');
const lineNumber = computed(() => props.graph?.nodeLineNumbers?.[props.nodeId] ?? null);
const filePath = computed(() => props.graph?.nodeFilePaths?.[props.nodeId] ?? null);
const nodeAliases = computed(() => props.graph?.nodeAliases?.[props.nodeId] ?? null);

const displayName = computed(() => {
  const aliases = nodeAliases.value;
  if (Array.isArray(aliases) && aliases.length > 0 && typeof aliases[0] === 'string' && aliases[0]) {
    return aliases[0];
  }
  const id = props.nodeId;
  const typ = nodeType.value;
  if (typ === 'entry' || id === 'entry' || id.endsWith('_entry')) return 'entry';
  if (typ === 'exit' || id === 'exit' || id.endsWith('_exit')) return 'exit';
  if (typ === 'Controller' || id.endsWith('_controller')) return 'controller';
  if (typ === 'TerminateNode' || id.endsWith('_terminate')) return 'terminate';
  return id;
});

const showRawId = computed(() => displayName.value !== props.nodeId);

const pullKeys = computed(() => props.graph?.nodePullKeys?.[props.nodeId]);
const pushKeys = computed(() => props.graph?.nodePushKeys?.[props.nodeId]);
const nodeAttributes = computed(() => props.graph?.nodeAttributes?.[props.nodeId]);
const inputKeys = computed(() => props.graph?.nodeInputKeys?.[props.nodeId]);
const outputKeys = computed(() => props.graph?.nodeOutputKeys?.[props.nodeId]);
const instructions = computed(() => props.graph?.nodeInstructions?.[props.nodeId]);
const promptTemplate = computed(() => props.graph?.nodePromptTemplates?.[props.nodeId]);

const runs = computed<NodeExecution[]>(() => {
  const list = props.exec.nodeHistory?.[props.nodeId] || [];
  return list
    .slice()
    .sort((a, b) => (b.startedAt || 0) - (a.startedAt || 0));
});

const selectedRunId = ref<string | null>(null);

watch(
  () => props.nodeId,
  () => {
    selectedRunId.value = runs.value[0]?.runId ?? null;
  },
  { immediate: true }
);

watch(
  () => runs.value.length,
  () => {
    if (!selectedRunId.value) {
      selectedRunId.value = runs.value[0]?.runId ?? null;
      return;
    }
    if (!runs.value.some((r) => r.runId === selectedRunId.value)) {
      selectedRunId.value = runs.value[0]?.runId ?? null;
    }
  }
);

const selectedRun = computed(() => {
  if (!selectedRunId.value) return runs.value[0] ?? null;
  return runs.value.find((r) => r.runId === selectedRunId.value) ?? runs.value[0] ?? null;
});

const debugState = computed(() => props.debug || null);
const isPausedHere = computed(() => {
  const d = debugState.value;
  if (!d || !d.paused) return false;
  const ids = d.pausedNodeIds || [];
  return Array.isArray(ids) && ids.includes(props.nodeId);
});
const isExceptionHere = computed(() => {
  const d = debugState.value;
  if (!d || !d.paused) return false;
  const ids = d.exceptionNodeIds || [];
  return Array.isArray(ids) && ids.includes(props.nodeId);
});

type EffectiveStatus = 'running' | 'ok' | 'error' | 'paused' | 'unknown';
const status = computed<EffectiveStatus>(() => {
  if (isExceptionHere.value) return 'error';
  if (isPausedHere.value) return 'paused';
  const s = selectedRun.value?.status;
  if (s === 'running' || s === 'ok' || s === 'error') return s;
  return 'unknown';
});
const statusLabel = computed(() => {
  const s = status.value;
  if (s === 'running') return 'RUNNING';
  if (s === 'paused') return 'PAUSED';
  if (s === 'ok') return 'OK';
  if (s === 'error') return 'ERROR';
  return '—';
});

const durationMs = computed<number | null>(() => {
  const r = selectedRun.value;
  if (!r) return null;
  if (!r.endedAt) return null;
  return Math.max(0, r.endedAt - r.startedAt);
});

const tokenUsage = computed(() => {
  const r = selectedRun.value;
  if (!r) return null;
  return extractTokenUsage(r.metrics) ?? extractTokenUsage(r.outputs) ?? extractTokenUsage(r.inputs);
});

function renderKeySemantics(value: unknown): {
  kind: 'unset' | 'none' | 'all' | 'map';
  map?: Record<string, unknown>;
} {
  if (value === undefined) return { kind: 'unset' };
  if (value === null) return { kind: 'all' };
  if (value === 'empty') return { kind: 'none' };
  if (value && typeof value === 'object' && !Array.isArray(value)) return { kind: 'map', map: value as any };
  return { kind: 'unset' };
}

function openSource() {
  if (!filePath.value) return;
  postMessage({
    type: 'openFileLocation',
    filePath: filePath.value,
    line: typeof lineNumber.value === 'number' ? lineNumber.value : undefined
  });
}
</script>

<template>
  <div class="root">
    <div class="header">
      <div class="title">
        <div class="node-id mono">{{ displayName }}</div>
        <div class="node-type">{{ nodeType }}</div>
        <div v-if="showRawId" class="meta mono">id {{ nodeId }}</div>
        <div v-if="lineNumber" class="meta mono">line {{ lineNumber }}</div>
        <div v-if="filePath" class="meta-row">
          <span class="meta mono">{{ filePath }}</span>
          <button class="open-link" @click="openSource">Open</button>
        </div>
      </div>

      <div class="stats">
        <div class="stat">
          <div class="k">Status</div>
          <div class="v status" :class="status">{{ statusLabel }}</div>
        </div>
        <div class="stat">
          <div class="k">Duration</div>
          <div class="v mono">{{ formatDurationMs(durationMs) }}</div>
        </div>
        <div class="stat">
          <div class="k">Tokens</div>
          <div class="v mono">{{ formatTokenUsage(tokenUsage) }}</div>
        </div>
        <div class="stat">
          <div class="k">Runs</div>
          <div class="v mono">{{ runs.length }}</div>
        </div>
      </div>
    </div>

    <div v-if="runs.length > 0" class="runs">
      <div class="runs-title">Execution History</div>
      <div class="runs-list">
        <button
          v-for="r in runs.slice(0, 10)"
          :key="r.runId"
          class="run"
          :class="{ active: selectedRunId === r.runId }"
          @click="selectedRunId = r.runId"
        >
          <span class="badge" :class="r.status">{{ r.status.toUpperCase() }}</span>
          <span class="mono">{{ new Date(r.startedAt).toLocaleTimeString() }}</span>
          <span v-if="r.endedAt" class="mono dim">{{ formatDurationMs(Math.max(0, r.endedAt - r.startedAt)) }}</span>
          <span v-else class="mono dim">—</span>
        </button>
      </div>
    </div>

    <div class="sections">
      <details open class="section">
        <summary class="section-title">Inputs</summary>
        <div class="section-body">
          <div v-if="!selectedRun || selectedRun.inputs === undefined" class="empty">—</div>
          <JsonTree v-else :value="selectedRun.inputs" :open="true" :dense="true" />
        </div>
      </details>

      <details open class="section">
        <summary class="section-title">Outputs</summary>
        <div class="section-body">
          <div v-if="!selectedRun || selectedRun.outputs === undefined" class="empty">—</div>
          <JsonTree v-else :value="selectedRun.outputs" :open="true" :dense="true" />
        </div>
      </details>

      <details v-if="selectedRun?.error" open class="section">
        <summary class="section-title">Error</summary>
        <div class="section-body">
          <pre class="mono error">{{ selectedRun.error }}</pre>
        </div>
      </details>

      <details open class="section">
        <summary class="section-title">Node Keys & Config</summary>
        <div class="section-body grid">
          <div class="block">
            <div class="block-title">pull_keys</div>
            <div v-if="renderKeySemantics(pullKeys).kind === 'all'" class="hint">None (all keys)</div>
            <div v-else-if="renderKeySemantics(pullKeys).kind === 'none'" class="hint">{} (no keys)</div>
            <div v-else-if="renderKeySemantics(pullKeys).kind === 'unset'" class="hint">—</div>
            <JsonTree
              v-else
              :value="renderKeySemantics(pullKeys).map"
              :open="true"
              :dense="true"
            />
          </div>

          <div class="block">
            <div class="block-title">push_keys</div>
            <div v-if="renderKeySemantics(pushKeys).kind === 'all'" class="hint">None (all keys)</div>
            <div v-else-if="renderKeySemantics(pushKeys).kind === 'none'" class="hint">{} (no keys)</div>
            <div v-else-if="renderKeySemantics(pushKeys).kind === 'unset'" class="hint">—</div>
            <JsonTree
              v-else
              :value="renderKeySemantics(pushKeys).map"
              :open="true"
              :dense="true"
            />
          </div>

          <div v-if="inputKeys" class="block">
            <div class="block-title">input_keys</div>
            <JsonTree :value="inputKeys" :open="true" :dense="true" />
          </div>

          <div v-if="outputKeys" class="block">
            <div class="block-title">output_keys</div>
            <JsonTree :value="outputKeys" :open="true" :dense="true" />
          </div>

          <div v-if="nodeAttributes" class="block">
            <div class="block-title">attributes</div>
            <JsonTree :value="nodeAttributes" :open="true" :dense="true" />
          </div>

          <div v-if="instructions" class="block wide">
            <div class="block-title">instructions</div>
            <pre class="mono text">{{ instructions }}</pre>
          </div>

          <div v-if="promptTemplate" class="block wide">
            <div class="block-title">prompt_template</div>
            <pre class="mono text">{{ promptTemplate }}</pre>
          </div>
        </div>
      </details>
    </div>
  </div>
</template>

<style scoped>
.root {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  padding: 10px;
}

.title {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.node-id {
  font-weight: 700;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-type {
  font-size: 12px;
  opacity: 0.85;
}

.meta {
  font-size: 11px;
  opacity: 0.75;
}

.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(86px, 1fr));
  gap: 10px;
  align-items: start;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.meta-row {
  display: flex;
  gap: 8px;
  align-items: baseline;
  min-width: 0;
}

.open-link {
  font-size: 11px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--vscode-textLink-foreground, #3794ff);
  cursor: pointer;
  flex-shrink: 0;
}

.open-link:hover {
  text-decoration: underline;
}

.k {
  font-size: 11px;
  opacity: 0.75;
}

.v {
  font-size: 12px;
}

.status {
  font-weight: 700;
  letter-spacing: 0.3px;
}

.status.running {
  color: #4fc3f7;
}

.status.paused {
  color: #d7ba7d;
}

.status.ok {
  color: #2d9f4c;
}

.status.error {
  color: #f48771;
}

.runs-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 6px;
  opacity: 0.9;
}

.runs-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.run {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  padding: 6px 8px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 999px;
  background: transparent;
  color: var(--vscode-editor-foreground);
  cursor: pointer;
  font-size: 11px;
}

.run:hover {
  background: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.06));
}

.run.active {
  border-color: rgba(14, 99, 156, 0.6);
  background: rgba(14, 99, 156, 0.12);
}

.badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 999px;
  border: 1px solid rgba(90, 90, 90, 0.35);
  opacity: 0.95;
}

.badge.running {
  color: #4fc3f7;
  border-color: rgba(79, 195, 247, 0.45);
}

.badge.ok {
  color: #2d9f4c;
  border-color: rgba(45, 159, 76, 0.45);
}

.badge.error {
  color: #f48771;
  border-color: rgba(244, 135, 113, 0.45);
}

.dim {
  opacity: 0.7;
}

.sections {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section {
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  overflow: hidden;
}

.section-title {
  cursor: pointer;
  padding: 8px 10px;
  background: var(--vscode-editor-background);
  font-weight: 600;
  font-size: 12px;
  list-style: none;
}

.section-title::-webkit-details-marker {
  display: none;
}

.section-title::before {
  content: '▸';
  width: 14px;
  display: inline-block;
  opacity: 0.75;
  transform: translateY(-1px);
}

details[open] > .section-title::before {
  content: '▾';
}

.section-body {
  padding: 10px;
}

.empty {
  opacity: 0.75;
  font-size: 12px;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.block {
  border: 1px solid rgba(90, 90, 90, 0.25);
  border-radius: 8px;
  padding: 10px;
  min-width: 0;
}

.block.wide {
  grid-column: 1 / -1;
}

.block-title {
  font-size: 11px;
  opacity: 0.75;
  margin-bottom: 8px;
}

.hint {
  opacity: 0.75;
  font-size: 12px;
}

.text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.4;
}

.error {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: #f48771;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
}
</style>
