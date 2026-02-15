<script setup lang="ts">
import { computed, ref, watch } from 'vue';

type Row = { k: string; v: string; id: string };

const props = defineProps<{
  value: Record<string, string> | null | undefined;
  keyLabel?: string;
  valueLabel?: string;
  emptyHint?: string;
  defaultHint?: string;
}>();

const emit = defineEmits<{
  (e: 'update:value', value: Record<string, string> | null | undefined): void;
}>();

function normalize(v: unknown): Record<string, string> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return {};
  const out: Record<string, string> = {};
  for (const [k, val] of Object.entries(v as any)) {
    out[String(k)] = val == null ? '' : String(val);
  }
  return out;
}

const draftRows = ref<Row[]>([]);
const draftIsDefault = ref<boolean>(false);

function fromObject(obj: Record<string, string>): Row[] {
  return Object.entries(obj).map(([k, v], idx) => ({
    k,
    v,
    id: `${idx}:${k}`
  }));
}

function toObject(r: Row[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of r) {
    const k = String(row.k || '').trim();
    if (!k) continue;
    out[k] = String(row.v ?? '');
  }
  return out;
}

function stableSignature(obj: Record<string, string>): string {
  const entries = Object.entries(obj).map(([k, v]) => [String(k), String(v ?? '')] as const);
  entries.sort((a, b) => a[0].localeCompare(b[0]));
  return JSON.stringify(entries);
}

const committedIsDefault = computed(() => props.value == null);
const committedObject = computed(() => (committedIsDefault.value ? {} : normalize(props.value)));

const draftObject = computed(() => toObject(draftRows.value));

const isDirty = computed(() => {
  if (draftIsDefault.value) return !committedIsDefault.value;
  if (committedIsDefault.value) return true;
  return stableSignature(draftObject.value) !== stableSignature(committedObject.value);
});

watch(
  () => props.value,
  (v) => {
    if (v == null) {
      draftIsDefault.value = true;
      draftRows.value = [];
      return;
    }
    draftIsDefault.value = false;
    const incoming = normalize(v);
    draftRows.value = fromObject(incoming);
  },
  { immediate: true, deep: true }
);

function addRow() {
  if (draftIsDefault.value) draftIsDefault.value = false;
  draftRows.value = [
    ...draftRows.value,
    { k: '', v: '', id: `new:${Date.now()}:${Math.random().toString(16).slice(2)}` }
  ];
}

function deleteRow(i: number) {
  if (draftIsDefault.value) return;
  const next = draftRows.value.slice();
  next.splice(i, 1);
  draftRows.value = next;
}

function updateRow(i: number, patch: Partial<Pick<Row, 'k' | 'v'>>) {
  if (draftIsDefault.value) draftIsDefault.value = false;
  draftRows.value = draftRows.value.map((r, idx) => (idx === i ? { ...r, ...patch } : r));
}

function setDefaultMode() {
  draftIsDefault.value = true;
  draftRows.value = [];
}

function commitDraft() {
  if (!isDirty.value) return;
  if (draftIsDefault.value) {
    emit('update:value', undefined);
    return;
  }
  emit('update:value', toObject(draftRows.value));
}

const hasRows = computed(() => draftRows.value.length > 0);
const keyLabel = computed(() => props.keyLabel || 'Key');
const valueLabel = computed(() => props.valueLabel || 'Value');
</script>

<template>
  <div class="root">
    <div class="table">
      <div class="toolbar">
        <div class="left">
          <span v-if="draftIsDefault" class="pill">Default</span>
          <span v-else class="pill secondary">Custom</span>
          <button
            v-if="!draftIsDefault"
            class="link mono"
            type="button"
            title="Switch back to default (unset this field)"
            @click.prevent.stop="setDefaultMode"
          >
            Use Default
          </button>
        </div>
        <div class="right">
          <button
            class="icon-btn"
            type="button"
            :disabled="!isDirty"
            title="Apply edits (commit to in-memory state)"
            @click.prevent.stop="commitDraft"
          >
            ✓
          </button>
        </div>
      </div>

      <div class="thead">
        <div class="th mono">{{ keyLabel }}</div>
        <div class="th mono">{{ valueLabel }}</div>
        <div class="th"></div>
      </div>

      <div v-if="!hasRows" class="empty">
        {{ (draftIsDefault ? defaultHint : emptyHint) || emptyHint || defaultHint || 'No entries.' }}
      </div>

      <div v-else class="tbody">
        <div v-for="(r, i) in draftRows" :key="r.id" class="row">
          <input
            class="cell input mono"
            :value="r.k"
            @input="(e:any)=>updateRow(i,{k:e.target.value})"
            @keydown.enter.prevent.stop="commitDraft"
            placeholder="key"
          />
          <input
            class="cell input mono"
            :value="r.v"
            @input="(e:any)=>updateRow(i,{v:e.target.value})"
            @keydown.enter.prevent.stop="commitDraft"
            placeholder="description/value"
          />
          <button class="cell btn secondary" type="button" title="Remove" @click.prevent.stop="deleteRow(i)">×</button>
        </div>
      </div>

      <button class="add-row" type="button" @click.prevent.stop="addRow">
        <span class="cell add-cell">
          <span class="plus">+</span>
          <span class="label mono">Add</span>
        </span>
        <span class="cell"></span>
        <span class="cell"></span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.root {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-bottom: 1px solid var(--vscode-panel-border, #2d2d2d);
  background: rgba(255, 255, 255, 0.03);
}

.left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pill {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(45, 159, 76, 0.14);
  border-color: rgba(45, 159, 76, 0.35);
  color: var(--vscode-editor-foreground);
  user-select: none;
  white-space: nowrap;
}

.pill.secondary {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.14);
}

.icon-btn {
  width: 28px;
  height: 28px;
  padding: 0;
  margin: 0;
  border-radius: 6px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  background: transparent;
  color: var(--vscode-editor-foreground);
  cursor: pointer;
}

.icon-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.06);
}

.icon-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.link {
  border: none;
  background: transparent;
  color: var(--vscode-textLink-foreground, #3794ff);
  cursor: pointer;
  padding: 0;
  font-size: 11px;
  opacity: 0.9;
  white-space: nowrap;
}

.link:hover {
  text-decoration: underline;
  opacity: 1;
}

.table {
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  overflow: hidden;
}

.thead {
  display: grid;
  grid-template-columns: 160px 1fr 32px;
  gap: 0;
  background: rgba(255, 255, 255, 0.04);
  border-bottom: 1px solid var(--vscode-panel-border, #2d2d2d);
}

.th {
  padding: 8px;
  font-size: 11px;
  opacity: 0.85;
}

.tbody {
  display: flex;
  flex-direction: column;
}

.row {
  display: grid;
  grid-template-columns: 160px 1fr 32px;
  gap: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.row:last-child {
  border-bottom: none;
}

.add-row {
  width: 100%;
  display: grid;
  grid-template-columns: 160px 1fr 32px;
  gap: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--vscode-editor-foreground);
  cursor: pointer;
  text-align: left;
}

.add-row:hover {
  background: rgba(255, 255, 255, 0.05);
}

.add-cell {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  opacity: 0.9;
}

.plus {
  font-size: 14px;
  line-height: 1;
  width: 14px;
  display: inline-flex;
  justify-content: center;
}

.cell {
  padding: 6px 8px;
  min-width: 0;
}

.input {
  border: none;
  outline: none;
  background: transparent;
  color: var(--vscode-editor-foreground);
  width: 100%;
  box-sizing: border-box;
}

.btn {
  width: 28px;
  height: 28px;
  padding: 0;
  margin: 0;
  border-radius: 6px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  background: transparent;
  color: var(--vscode-editor-foreground);
  cursor: pointer;
}

.btn:hover {
  background: rgba(255, 255, 255, 0.06);
}

.btn.secondary {
  background: transparent;
  color: var(--vscode-editor-foreground);
  border-color: var(--vscode-panel-border, #2d2d2d);
}

.btn.secondary:hover {
  background: rgba(255, 255, 255, 0.06);
}

.empty {
  padding: 10px;
  opacity: 0.75;
  font-size: 12px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
}
</style>
