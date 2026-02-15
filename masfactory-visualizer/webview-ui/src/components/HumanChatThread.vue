<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { useRuntimeStore } from '../stores/runtime';

import type { HumanInteractionRequest, HumanChatMessage } from '../stores/runtime';

const props = defineProps<{
  sessionId: string;
}>();

const runtime = useRuntimeStore();

const chat = computed(() => runtime.humanChatForSession(props.sessionId));
const pendingCount = computed(() => runtime.humanPendingCount(props.sessionId));
const requests = computed<HumanInteractionRequest[]>(() => runtime.humanRequestsForSession(props.sessionId));
const requestById = computed(() => {
  const map = new Map<string, HumanInteractionRequest>();
  for (const r of requests.value) {
    if (!r?.requestId) continue;
    map.set(r.requestId, r);
  }
  return map;
});
const nextPending = computed(() => requests.value.find((r) => r && !r.resolved) || null);

const input = ref('');
const listRef = ref<HTMLDivElement | null>(null);

function scrollToBottom() {
  const el = listRef.value;
  if (!el) return;
  el.scrollTop = el.scrollHeight;
}

async function afterUpdateScroll() {
  await nextTick();
  scrollToBottom();
}

function send() {
  const text = input.value;
  if (!text.trim()) return;
  const ok = runtime.respondToNextHumanRequest(props.sessionId, text);
  if (!ok) return;
  input.value = '';
  void afterUpdateScroll();
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

function initials(raw: string | undefined | null, fallback: string): string {
  const value = typeof raw === 'string' ? raw.trim() : '';
  if (!value) return fallback;
  const parts = value
    .split(/[^a-zA-Z0-9]+/)
    .map((p) => p.trim())
    .filter(Boolean);
  const letters = parts.map((p) => p.slice(0, 1).toUpperCase()).join('');
  return (letters || value.slice(0, 2)).slice(0, 2).toUpperCase();
}

function extractContextFromPrompt(prompt: string): string | null {
  if (!prompt) return null;
  const marker = 'Context (incoming message):';
  const idx = prompt.indexOf(marker);
  if (idx === -1) return null;
  let tail = prompt.slice(idx + marker.length);
  // Consume leading newlines/spaces.
  tail = tail.replace(/^\s*\n/, '').replace(/^\s+/, '');

  const stopMarkers = ['\n\nPlease reply', '\n\nTip:', '\n\nPlease'];
  let stop = -1;
  for (const m of stopMarkers) {
    const j = tail.indexOf(m);
    if (j !== -1) {
      stop = stop === -1 ? j : Math.min(stop, j);
    }
  }
  const body = (stop === -1 ? tail : tail.slice(0, stop)).trim();
  return body ? body : null;
}

function displayAssistantMessage(m: HumanChatMessage): string {
  const req = m.requestId ? requestById.value.get(m.requestId) : undefined;
  const desc = typeof req?.description === 'string' ? req.description.trim() : '';
  const ctx = extractContextFromPrompt(m.content);
  const parts: string[] = [];
  if (desc) parts.push(desc);
  if (ctx) parts.push(ctx);
  if (parts.length > 0) return parts.join('\n\n');
  return m.content;
}

function displayMessage(m: HumanChatMessage): string {
  if (m.role === 'assistant') return displayAssistantMessage(m);
  return m.content;
}

const composerPlaceholder = computed(() => {
  const req = nextPending.value;
  if (!req) return 'No pending requests';
  const node = req.node ? String(req.node) : 'Human';
  const field = req.field ? String(req.field) : '';
  const hint = field ? `${node}.${field}` : node;
  return `Reply to ${hint}… (Enter to send, Shift+Enter for newline)`;
});

watch(
  () => chat.value.length,
  () => {
    void afterUpdateScroll();
  }
);

onMounted(() => {
  void afterUpdateScroll();
});
</script>

<template>
  <div class="root">
    <div ref="listRef" class="chat">
      <div v-if="chat.length === 0" class="empty">No messages yet.</div>

      <div v-for="m in chat" :key="m.id" class="row" :class="m.role">
        <div v-if="m.role === 'assistant'" class="avatar assistant" :title="m.node ?? 'Agent'">
          {{ initials(m.node, 'AG') }}
        </div>

        <div class="bubble-wrap">
          <div class="meta">
            <span class="name">{{ m.role === 'assistant' ? (m.node ?? 'Agent') : 'You' }}</span>
            <span v-if="m.field" class="dot">·</span>
            <span v-if="m.field" class="field">{{ m.field }}</span>
            <span class="dot">·</span>
            <span class="ts">{{ new Date(m.ts).toLocaleTimeString() }}</span>
          </div>
          <pre class="bubble">{{ displayMessage(m) }}</pre>
        </div>

        <div v-if="m.role === 'user'" class="avatar user" title="You">
          {{ initials('You', 'U') }}
        </div>
      </div>
    </div>

    <div class="composer">
      <textarea
        v-model="input"
        class="input"
        rows="2"
        :placeholder="composerPlaceholder"
        :disabled="pendingCount === 0"
        @keydown="onKeydown"
      />
      <button class="btn" :disabled="pendingCount === 0 || !input.trim()" @click="send">Send</button>
    </div>
  </div>
</template>

<style scoped>
.root {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.chat {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 10px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 10px;
  background: var(--vscode-editor-background);
}

.empty {
  opacity: 0.75;
  font-size: 12px;
}

.row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
  align-items: flex-end;
}

.row:last-child {
  margin-bottom: 0;
}

.row.user {
  justify-content: flex-end;
}

.bubble-wrap {
  max-width: min(680px, 74%);
  min-width: 0;
}

.row.user .bubble-wrap {
  text-align: right;
}

.meta {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  font-size: 11px;
  opacity: 0.82;
  margin-bottom: 4px;
  max-width: 100%;
}

.name {
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 240px;
}

.dot {
  opacity: 0.6;
}

.field {
  opacity: 0.9;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}

.ts {
  opacity: 0.75;
}

.bubble {
  margin: 0;
  padding: 10px 12px;
  border-radius: 14px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.35;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  background: rgba(14, 99, 156, 0.10);
  text-align: left;
}

.row.user .bubble {
  background: rgba(47, 159, 76, 0.10);
}

.avatar {
  width: 28px;
  height: 28px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  user-select: none;
}

.avatar.assistant {
  background: rgba(14, 99, 156, 0.25);
  color: #9cdcfe;
}

.avatar.user {
  background: rgba(47, 159, 76, 0.22);
  color: #b5cea8;
}

.composer {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.input {
  flex: 1;
  min-width: 0;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  background: var(--vscode-input-background, #1e1e1e);
  color: var(--vscode-input-foreground, #d4d4d4);
  resize: vertical;
}

.btn {
  font-size: 12px;
  padding: 7px 12px;
  border-radius: 10px;
  border: 1px solid var(--vscode-button-border, transparent);
  background: var(--vscode-button-background, #0e639c);
  color: var(--vscode-button-foreground, #fff);
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn:not(:disabled):hover {
  background: var(--vscode-button-hoverBackground, #1177bb);
}
</style>

