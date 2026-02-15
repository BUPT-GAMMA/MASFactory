<script setup lang="ts">
import { computed } from 'vue';

defineOptions({ name: 'JsonTree' });

const props = defineProps<{
  value: unknown;
  label?: string;
  open?: boolean;
  dense?: boolean;
}>();

function isPrimitive(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  );
}

function formatPrimitive(value: unknown): string {
  if (value === undefined) return 'undefined';
  if (value === null) return 'null';
  if (typeof value === 'string') return value;
  return String(value);
}

const isArray = computed(() => Array.isArray(props.value));
const isObject = computed(
  () => !!props.value && typeof props.value === 'object' && !Array.isArray(props.value)
);

const objectKeys = computed(() => {
  if (!isObject.value) return [];
  try {
    return Object.keys(props.value as any).sort((a, b) => a.localeCompare(b));
  } catch {
    return [];
  }
});

const summaryText = computed(() => {
  if (props.value === null) return 'null';
  if (props.value === undefined) return 'undefined';
  if (isArray.value) return `Array(${(props.value as any[]).length})`;
  if (isObject.value) return `Object(${objectKeys.value.length})`;
  if (typeof props.value === 'string') return `"${props.value.length > 80 ? props.value.slice(0, 80) + '…' : props.value}"`;
  return String(props.value);
});

const shouldUseDetails = computed(() => isArray.value || isObject.value);
</script>

<template>
  <div class="root" :class="{ dense: !!dense }">
    <div v-if="!shouldUseDetails" class="row">
      <span v-if="label" class="key mono">{{ label }}</span>
      <span v-if="label" class="sep">:</span>
      <span class="val mono" :class="{ empty: value === undefined || value === null }">
        {{ formatPrimitive(value) }}
      </span>
    </div>

    <details v-else class="details" :open="open ?? false">
      <summary class="summary">
        <span v-if="label" class="key mono">{{ label }}</span>
        <span v-if="label" class="sep">:</span>
        <span class="hint mono">{{ summaryText }}</span>
      </summary>
      <div class="children">
        <template v-if="isArray">
          <div v-for="(item, idx) in (value as any[])" :key="idx" class="child">
            <JsonTree :value="item" :label="String(idx)" :dense="dense" />
          </div>
        </template>
        <template v-else>
          <div v-for="k in objectKeys" :key="k" class="child">
            <JsonTree :value="(value as any)[k]" :label="k" :dense="dense" />
          </div>
        </template>
      </div>
    </details>
  </div>
</template>

<style scoped>
.root {
  min-width: 0;
}

.row {
  display: flex;
  gap: 6px;
  align-items: baseline;
  min-width: 0;
}

.key {
  opacity: 0.9;
  flex: 0 0 auto;
}

.sep {
  opacity: 0.6;
}

.val {
  opacity: 0.95;
  word-break: break-word;
}

.val.empty {
  opacity: 0.65;
}

.details {
  border-left: 1px solid rgba(90, 90, 90, 0.35);
  padding-left: 8px;
}

.summary {
  cursor: pointer;
  list-style: none;
  display: flex;
  gap: 6px;
  align-items: baseline;
}

.summary::-webkit-details-marker {
  display: none;
}

.summary::before {
  content: '▸';
  width: 14px;
  display: inline-block;
  opacity: 0.75;
  transform: translateY(-1px);
}

details[open] > .summary::before {
  content: '▾';
}

.hint {
  opacity: 0.75;
  word-break: break-word;
}

.children {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
  padding-left: 6px;
}

.child {
  min-width: 0;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
}

.dense .children {
  gap: 4px;
}
</style>

