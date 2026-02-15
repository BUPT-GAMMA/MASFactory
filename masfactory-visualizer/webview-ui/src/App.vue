<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useUiStore } from './stores/ui';
import PreviewTab from './components/PreviewTab.vue';
import DebugTab from './components/DebugTab.vue';
import RunTab from './components/RunTab.vue';
import VibeTab from './components/VibeTab.vue';
import SessionDetail from './components/SessionDetail.vue';
import HumanChatPopup from './components/HumanChatPopup.vue';
import ChatSessionPicker, { type ChatSessionEntry } from './components/ChatSessionPicker.vue';
import { onVsCodeMessage, postMessage } from './bridge/vscode';
import { dispatchVsCodeMessage } from './bridge/dispatch';
import { useRuntimeStore } from './stores/runtime';
import { useVibeStore } from './stores/vibe';
import { usePreviewStore } from './stores/preview';

const ui = useUiStore();
const activeTab = computed(() => ui.activeTab);
const runBadgeCount = computed(() => ui.unreadRunSessionIds.length);
const runtime = useRuntimeStore();
const vibe = useVibeStore();
const preview = usePreviewStore();

const chatSessionIds = computed(() => {
  const ids = new Set<string>();
  for (const s of runtime.sessions) ids.add(s.id);
  for (const id of Object.keys(runtime.humanRequests || {})) ids.add(id);
  for (const id of Object.keys(runtime.humanChats || {})) ids.add(id);
  return Array.from(ids);
});

const chatCandidateIds = computed(() =>
  chatSessionIds.value.filter(
    (id) => runtime.humanPendingCount(id) > 0 || runtime.humanChatForSession(id).length > 0
  )
);
const chatBadgeCount = computed(() => chatCandidateIds.value.length);
const hasAnyChat = computed(() =>
  chatCandidateIds.value.some(
    (id) => runtime.humanPendingCount(id) > 0 || runtime.humanChatForSession(id).length > 0
  )
);

function pickDefaultChatSessionId(): string | null {
  if (ui.chatSessionId && chatCandidateIds.value.includes(ui.chatSessionId)) return ui.chatSessionId;
  if (runtime.selectedRunSessionId && chatCandidateIds.value.includes(runtime.selectedRunSessionId))
    return runtime.selectedRunSessionId;
  if (runtime.selectedSessionId && chatCandidateIds.value.includes(runtime.selectedSessionId))
    return runtime.selectedSessionId;

  const pendingIds = chatCandidateIds.value.filter((id) => runtime.humanPendingCount(id) > 0);
  if (pendingIds.length > 0) return pendingIds[0];

  const sorted = runtime.sessions
    .slice()
    .sort((a, b) => (Number(b.lastSeenAt) || 0) - (Number(a.lastSeenAt) || 0));
  const firstAlive = sorted.find((s) => chatCandidateIds.value.includes(s.id))?.id || null;
  if (firstAlive) return firstAlive;
  if (chatCandidateIds.value.length > 0) return chatCandidateIds.value[0];
  return null;
}

const chatPickerVisible = ref(false);
const chatPickerEntries = computed<ChatSessionEntry[]>(() => {
  return chatCandidateIds.value
    .map((id) => {
      const s =
        runtime.sessions.find((x) => x.id === id) || (runtime.archivedSessions?.[id] as any) || null;
      const graphName = (s?.graphName as string | null) ?? '(unknown graph)';
      const mode = (s?.mode as string | null) ?? 'unknown';
      const pid = typeof s?.pid === 'number' ? (s.pid as number) : null;
      const lastSeenAt = typeof s?.lastSeenAt === 'number' ? (s.lastSeenAt as number) : 0;
      return {
        id,
        graphName,
        mode,
        pid,
        lastSeenAt,
        pendingCount: runtime.humanPendingCount(id),
        messageCount: runtime.humanChatForSession(id).length,
        isAlive: runtime.isSessionAlive(id)
      };
    })
    .sort((a, b) => (Number(b.lastSeenAt) || 0) - (Number(a.lastSeenAt) || 0));
});

function openChatPicker(): void {
  chatPickerVisible.value = true;
}

function closeChatPicker(): void {
  chatPickerVisible.value = false;
}

function selectChatSession(sessionId: string): void {
  closeChatPicker();
  ui.openChat(sessionId);
}

function deleteChatSession(sessionId: string): void {
  runtime.deleteChatSession(sessionId);
  if (ui.chatSessionId === sessionId) {
    const next = pickDefaultChatSessionId();
    if (next) ui.openChat(next);
    else ui.closeChat();
  }
}

function toggleGlobalChat(): void {
  if (ui.chatPopupVisible) {
    ui.hideChat();
    return;
  }
  const candidates = chatCandidateIds.value;
  if (candidates.length === 0) return;
  if (candidates.length === 1) {
    ui.toggleChat(candidates[0]);
    return;
  }
  openChatPicker();
}

const lastPendingBySession = new Map<string, number>();
watch(
  () => {
    const lastSeenById = new Map<string, number>();
    for (const s of runtime.sessions) {
      lastSeenById.set(s.id, typeof s.lastSeenAt === 'number' ? s.lastSeenAt : 0);
    }
    return chatSessionIds.value
      .map((id) => ({
        id,
        pending: runtime.humanPendingCount(id),
        lastSeenAt: lastSeenById.get(id) ?? 0
      }))
      .sort((a, b) => a.id.localeCompare(b.id));
  },
  (next) => {
    // Cleanup removed ids.
    const nextIds = new Set(next.map((x) => x.id));
    for (const id of Array.from(lastPendingBySession.keys())) {
      if (!nextIds.has(id)) lastPendingBySession.delete(id);
    }

    let candidate: { id: string; lastSeenAt: number } | null = null;
    for (const row of next) {
      const prev = lastPendingBySession.get(row.id) ?? 0;
      lastPendingBySession.set(row.id, row.pending);
      if (row.pending > prev && row.pending > 0) {
        if (!candidate || row.lastSeenAt >= candidate.lastSeenAt) {
          candidate = { id: row.id, lastSeenAt: row.lastSeenAt };
        }
      }
    }

    if (!candidate) return;
    // Avoid surprising session switches: only auto-open when the popup is hidden.
    if (!ui.chatPopupVisible) {
      ui.openChat(candidate.id);
    }
  },
  { immediate: true }
);

watch(
  () => [chatCandidateIds.value.slice().sort(), ui.chatSessionId, ui.chatPopupVisible] as const,
  ([ids, sid, visible]) => {
    if (visible && sid && !ids.includes(sid)) {
      // Session disappeared or chat was deleted; close or fall back.
      const next = pickDefaultChatSessionId();
      if (next) ui.openChat(next);
      else ui.closeChat();
    }
    if (visible && ids.length === 0) {
      ui.closeChat();
    }
  }
);

declare global {
  interface Window {
    __MASFACTORY_VISUALIZER_BOOTSTRAP?: unknown;
    __MASFACTORY_VISUALIZER_META?: unknown;
  }
}

type BootstrapPayload = { kind: 'runtime-session'; sessionId: string };

function getBootstrap(): BootstrapPayload | null {
  const raw = window.__MASFACTORY_VISUALIZER_BOOTSTRAP;
  if (!raw || typeof raw !== 'object') return null;
  const any = raw as any;
  if (any.kind === 'runtime-session' && typeof any.sessionId === 'string' && any.sessionId) {
    return { kind: 'runtime-session', sessionId: any.sessionId };
  }
  return null;
}

const bootstrap = getBootstrap();
const isRuntimeSessionPanel = computed(() => bootstrap?.kind === 'runtime-session');

const fatalError = ref<string | null>(null);

function getAppVersion(): string | null {
  const raw = window.__MASFACTORY_VISUALIZER_META;
  if (!raw || typeof raw !== 'object') return null;
  const any = raw as any;
  if (typeof any.version === 'string' && any.version.trim()) return any.version.trim();
  return null;
}

const titleText = computed(() => {
  const version = getAppVersion();
  return version ? `MASFactory Visualizer v${version}` : 'MASFactory Visualizer';
});

function formatUnknownError(err: unknown): string {
  if (err instanceof Error) return err.stack || err.message;
  if (typeof err === 'string') return err;
  try {
    return JSON.stringify(err);
  } catch {
    return String(err);
  }
}

function recordFatalError(context: string, err: unknown): void {
  const msg = `[${context}] ${formatUnknownError(err)}`;
  fatalError.value = msg;
  // eslint-disable-next-line no-console
  console.error('[MASFactory Visualizer][webview-ui] fatal error:', msg, err);
}

onMounted(() => {
  ui.restoreChatState();

  window.addEventListener('error', (evt) => {
    if (!evt) return;
    const err = (evt as any).error ?? (evt as any).message ?? evt;
    recordFatalError('window.error', err);
  });
  window.addEventListener('unhandledrejection', (evt) => {
    if (!evt) return;
    recordFatalError('unhandledrejection', (evt as any).reason ?? evt);
  });

  // Tell extension that Vue runtime UI is ready to receive state.
  postMessage({ type: 'runtimeWebviewReady' });
  if (!isRuntimeSessionPanel.value) {
    postMessage({ type: 'webviewReady' });
  }

  if (bootstrap?.kind === 'runtime-session') {
    runtime.pinSession(bootstrap.sessionId);
  }

      onVsCodeMessage((data) => {
    dispatchVsCodeMessage(
      data,
      {
        ui: {
          setActiveTab: (tab) => ui.setActiveTab(tab),
          markRunActivity: (sessionId) => ui.markRunActivity(sessionId)
        },
        runtime,
        vibe,
        preview
      },
      recordFatalError
    );
  });
});
</script>

<template>
  <div v-if="fatalError" class="fatal mono">
    <div class="fatal-title">MASFactory Visualizer UI Error</div>
    <pre class="fatal-body">{{ fatalError }}</pre>
    <div class="fatal-hint">Open the VS Code Developer Tools console for more details.</div>
  </div>

  <div v-if="isRuntimeSessionPanel" class="runtime-session">
    <SessionDetail
      v-if="bootstrap && bootstrap.kind === 'runtime-session'"
      :session-id="bootstrap.sessionId"
      :show-back="false"
      :show-open-in-tab="true"
      :open-in-tab-disabled="true"
      open-in-tab-label="Opened in Tab"
    />
  </div>

  <div v-else class="app">
    <header class="topbar">
      <div class="title">{{ titleText }}</div>
      <nav class="tabs" role="tablist" aria-label="MASFactory Visualizer Tabs">
        <button
          class="tab"
          :class="{ active: activeTab === 'preview' }"
          role="tab"
          :aria-selected="activeTab === 'preview'"
          @click="ui.setActiveTab('preview')"
        >
          Preview
        </button>
        <button
          class="tab"
          :class="{ active: activeTab === 'debug' }"
          role="tab"
          :aria-selected="activeTab === 'debug'"
          @click="ui.setActiveTab('debug')"
        >
          Debug
        </button>
        <button
          class="tab"
          :class="{ active: activeTab === 'run' }"
          role="tab"
          :aria-selected="activeTab === 'run'"
          @click="ui.setActiveTab('run')"
        >
          Run
          <span v-if="runBadgeCount > 0" class="tab-badge mono">{{ runBadgeCount }}</span>
        </button>
        <button
          class="tab"
          :class="{ active: activeTab === 'vibe' }"
          role="tab"
          :aria-selected="activeTab === 'vibe'"
          @click="ui.setActiveTab('vibe')"
        >
          Vibe
        </button>
      </nav>
      <div class="top-actions">
        <button
          class="tab"
          :disabled="!hasAnyChat"
          title="Show/Hide Human chat window"
          @click="toggleGlobalChat"
        >
          Chat
          <span v-if="chatBadgeCount > 0" class="tab-badge mono">{{ chatBadgeCount }}</span>
        </button>
      </div>
    </header>

    <section class="content">
      <div class="pane" v-show="activeTab === 'preview'">
        <PreviewTab :visible="activeTab === 'preview'" />
      </div>

      <div class="pane" v-show="activeTab === 'debug'">
        <DebugTab />
      </div>

      <div class="pane" v-show="activeTab === 'run'">
        <RunTab />
      </div>

      <div class="pane" v-show="activeTab === 'vibe'">
        <VibeTab />
      </div>
    </section>
  </div>

  <Teleport to="body">
    <HumanChatPopup
      v-if="ui.chatPopupVisible && ui.chatSessionId"
      :session-id="ui.chatSessionId"
      @hide="ui.hideChat"
    />
  </Teleport>

  <Teleport to="body">
    <ChatSessionPicker
      v-if="chatPickerVisible"
      :entries="chatPickerEntries"
      @close="closeChatPicker"
      @select="selectChatSession"
      @delete="deleteChatSession"
    />
  </Teleport>
</template>

<style scoped>
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
}

.fatal {
  height: 100vh;
  padding: 16px;
  box-sizing: border-box;
  color: var(--vscode-editor-foreground);
  background: var(--vscode-editor-background);
}

.fatal-title {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 10px;
}

.fatal-body {
  margin: 0;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid rgba(244, 135, 113, 0.35);
  background: rgba(244, 135, 113, 0.12);
  white-space: pre-wrap;
  overflow: auto;
  max-height: 60vh;
}

.fatal-hint {
  margin-top: 10px;
  opacity: 0.8;
  font-size: 12px;
}

.app {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--vscode-panel-border, #2d2d2d);
  background: var(--vscode-editor-background);
}

.title {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.2px;
  color: var(--vscode-editor-foreground);
  user-select: none;
}

.tabs {
  display: inline-flex;
  gap: 6px;
}

.top-actions {
  margin-left: auto;
  display: flex;
  gap: 6px;
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

.tab-badge {
  margin-left: 6px;
  font-size: 11px;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 999px;
  border: 1px solid rgba(215, 186, 125, 0.6);
  background: rgba(215, 186, 125, 0.18);
  color: var(--vscode-editor-foreground);
}

.tab:hover {
  background: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.06));
}

.tab.active {
  background: var(--vscode-button-background, #0e639c);
  color: var(--vscode-button-foreground, #ffffff);
}

.content {
  flex: 1;
  position: relative;
  min-height: 0;
}

.pane {
  position: absolute;
  inset: 0;
}

.runtime-session {
  width: 100vw;
  height: 100vh;
}

.placeholder {
  padding: 16px;
  color: var(--vscode-descriptionForeground, rgba(212, 212, 212, 0.75));
}
</style>
