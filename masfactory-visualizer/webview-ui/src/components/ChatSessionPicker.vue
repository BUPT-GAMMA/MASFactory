<script setup lang="ts">
import { computed } from 'vue';

export type ChatSessionEntry = {
  id: string;
  graphName: string;
  mode: string;
  pid: number | null;
  lastSeenAt: number;
  pendingCount: number;
  messageCount: number;
  isAlive: boolean;
};

const props = defineProps<{
  entries: ChatSessionEntry[];
}>();

const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'select', sessionId: string): void;
  (e: 'delete', sessionId: string): void;
}>();

const sorted = computed(() =>
  (props.entries || [])
    .slice()
    .sort((a, b) => (Number(b.lastSeenAt) || 0) - (Number(a.lastSeenAt) || 0))
);

function close(): void {
  emit('close');
}

function select(sessionId: string): void {
  emit('select', sessionId);
}

function del(sessionId: string): void {
  emit('delete', sessionId);
}

function formatTime(ts: number): string {
  if (!ts || !Number.isFinite(ts)) return '—';
  try {
    return new Date(ts).toLocaleTimeString();
  } catch {
    return '—';
  }
}

function onBackdropPointerDown(e: PointerEvent): void {
  const target = e.target as HTMLElement | null;
  if (!target) return;
  if (target.closest('.modal')) return;
  close();
}
</script>

<template>
  <div class="backdrop" role="dialog" aria-label="Chat Sessions" @pointerdown="onBackdropPointerDown">
    <div class="modal">
      <div class="header">
        <div class="title">Chat Sessions</div>
        <button class="btn secondary" @click="close">Close</button>
      </div>

      <div v-if="sorted.length === 0" class="empty">No chats.</div>

      <div v-else class="list" role="list">
        <div
          v-for="s in sorted"
          :key="s.id"
          class="row"
          role="listitem"
          :class="{ attention: s.pendingCount > 0 }"
        >
          <button class="main" @click="select(s.id)">
            <div class="top">
              <span class="graph">{{ s.graphName }}</span>
              <span class="badge mono">{{ s.mode }}</span>
              <span v-if="!s.isAlive" class="badge exited">exited</span>
              <span v-if="s.pendingCount > 0" class="badge human">Human {{ s.pendingCount }}</span>
            </div>
            <div class="sub mono">
              <span>PID: {{ s.pid ?? '—' }}</span>
              <span class="dot">·</span>
              <span>Last: {{ formatTime(s.lastSeenAt) }}</span>
              <span class="dot">·</span>
              <span>Msgs: {{ s.messageCount }}</span>
              <span class="dot">·</span>
              <span class="id">{{ s.id }}</span>
            </div>
          </button>

          <div class="actions">
            <button
              v-if="!s.isAlive"
              class="btn danger"
              title="Delete this chat history"
              @click="del(s.id)"
            >
              Delete
            </button>
          </div>
        </div>
      </div>

      <div class="hint">
        <div class="hint-title">Tip</div>
        <div class="hint-body">Use the Run tab to delete ended processes.</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
}

.backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
}

.modal {
  width: min(920px, 100%);
  max-height: min(720px, 100%);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 12px;
  background: var(--vscode-editor-background);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
  overflow: hidden;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--vscode-panel-border, #2d2d2d);
}

.title {
  font-size: 13px;
  font-weight: 700;
}

.empty {
  padding: 14px;
  opacity: 0.85;
}

.list {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
}

.row {
  display: flex;
  gap: 10px;
  align-items: center;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.02);
}

.row.attention {
  border-color: rgba(215, 186, 125, 0.75);
}

.main {
  flex: 1;
  text-align: left;
  background: transparent;
  border: 0;
  color: var(--vscode-editor-foreground);
  padding: 10px 10px 10px 12px;
  cursor: pointer;
  min-width: 0;
}

.main:hover {
  background: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.06));
}

.top {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.graph {
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(14, 99, 156, 0.35);
  background: rgba(14, 99, 156, 0.25);
}

.badge.exited {
  border-color: rgba(120, 120, 120, 0.5);
  background: rgba(120, 120, 120, 0.18);
  opacity: 0.9;
}

.badge.human {
  border-color: rgba(215, 186, 125, 0.55);
  background: rgba(215, 186, 125, 0.16);
}

.sub {
  margin-top: 6px;
  font-size: 11px;
  opacity: 0.85;
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.dot {
  opacity: 0.6;
}

.id {
  opacity: 0.8;
}

.actions {
  padding: 10px 12px 10px 0;
  display: flex;
  gap: 8px;
}

.btn {
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid var(--vscode-button-border, transparent);
  background: var(--vscode-button-background, #0e639c);
  color: var(--vscode-button-foreground, #fff);
  cursor: pointer;
}

.btn.secondary {
  background: transparent;
  color: var(--vscode-editor-foreground);
  border-color: var(--vscode-panel-border, #2d2d2d);
}

.btn.secondary:hover {
  background: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.06));
}

.btn.danger {
  background: rgba(244, 135, 113, 0.16);
  border-color: rgba(244, 135, 113, 0.35);
  color: var(--vscode-editor-foreground);
}

.btn.danger:hover {
  background: rgba(244, 135, 113, 0.24);
}

.hint {
  border-top: 1px solid var(--vscode-panel-border, #2d2d2d);
  padding: 10px 12px;
  font-size: 11px;
  opacity: 0.9;
}

.hint-title {
  font-weight: 700;
  margin-bottom: 4px;
}
</style>
