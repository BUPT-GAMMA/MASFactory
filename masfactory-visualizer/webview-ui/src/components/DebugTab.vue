<script setup lang="ts">
import { computed } from 'vue';
import { useRuntimeStore } from '../stores/runtime';
import SessionDetail from './SessionDetail.vue';

const runtime = useRuntimeStore();
const sessions = computed(() => runtime.debugSessions);
const selectedId = computed(() => runtime.selectedSessionId);

function selectSession(id: string) {
  runtime.selectDebugSession(id);
}

function backToList() {
  runtime.clearDebugSelection();
}
</script>

<template>
  <div class="tab-root">
    <div class="header">
      <div class="title">Debug</div>
      <div class="meta">MASFACTORY_VISUALIZER_PORT: {{ runtime.port ?? '—' }}</div>
    </div>

    <div v-if="sessions.length === 0 && !selectedId" class="empty">No debug sessions connected.</div>

    <!-- No selection: keep full list -->
    <div v-else-if="!selectedId" class="list">
      <div
        v-for="s in sessions"
        :key="s.id"
        class="row"
        :class="{ attention: runtime.humanPendingCount(s.id) > 0 }"
        @contextmenu.prevent
      >
        <div class="main">
          <div class="name">
            {{ s.graphName ?? '(unknown graph)' }}
            <span v-if="runtime.humanPendingCount(s.id) > 0" class="attention-badge">Human</span>
          </div>
          <div class="sub">PID: {{ s.pid ?? '—' }} · {{ s.id }}</div>
        </div>
        <div class="actions">
          <button class="btn" @click="selectSession(s.id)">View</button>
          <button class="btn secondary" @click="runtime.openSessionInTab(s.id)">Open Tab</button>
        </div>
      </div>
    </div>

    <!-- Selected: sidebar + detail -->
    <div v-else class="layout">
      <aside class="sidebar">
        <button
          v-for="s in sessions"
          :key="s.id"
          class="session"
          :class="{
            active: selectedId === s.id,
            attention: runtime.humanPendingCount(s.id) > 0
          }"
          @click="selectSession(s.id)"
          @contextmenu.prevent
        >
          <div class="name">{{ s.graphName ?? '(unknown graph)' }}</div>
          <div class="sub">PID: {{ s.pid ?? '—' }} · {{ s.id }}</div>
        </button>
      </aside>

      <section class="main">
        <SessionDetail :session-id="selectedId" :show-back="true" @back="backToList" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.tab-root {
  height: 100%;
  padding: 12px;
  box-sizing: border-box;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 10px;
}

.title {
  font-size: 14px;
  font-weight: 600;
}

.meta {
  font-size: 12px;
  opacity: 0.8;
}

.layout {
  display: flex;
  gap: 10px;
  height: calc(100% - 34px);
  min-height: 0;
}

.sidebar {
  width: 260px;
  min-width: 260px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: auto;
  border-right: 1px solid var(--vscode-panel-border, #2d2d2d);
  padding-right: 10px;
}

.session {
  text-align: left;
  padding: 10px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  background: transparent;
  color: var(--vscode-editor-foreground);
  cursor: pointer;
}

.session:hover {
  background: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.06));
}

.session.active {
  border-color: rgba(14, 99, 156, 0.6);
  background: rgba(14, 99, 156, 0.12);
}

.session.attention:not(.active) {
  border-color: rgba(215, 186, 125, 0.75);
  background: rgba(215, 186, 125, 0.08);
}

.session.attention:not(.active):hover {
  background: rgba(215, 186, 125, 0.12);
}

.name {
  font-weight: 600;
}

.attention-badge {
  margin-left: 8px;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(215, 186, 125, 0.55);
  background: rgba(215, 186, 125, 0.16);
}

.sub {
  margin-top: 4px;
  font-size: 12px;
  opacity: 0.8;
}

.main {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.empty {
  padding: 10px;
  opacity: 0.8;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.row {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 10px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  background: var(--vscode-editor-background);
}

.row.attention {
  border-color: rgba(215, 186, 125, 0.75);
  animation: attentionPulse 1.2s ease-in-out infinite;
}

.actions {
  display: flex;
  gap: 8px;
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

.btn.secondary {
  background: transparent;
  color: var(--vscode-editor-foreground);
  border-color: var(--vscode-panel-border, #2d2d2d);
}

.btn.secondary:hover {
  background: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.06));
}

@keyframes attentionPulse {
  0% {
    box-shadow: 0 0 0 rgba(215, 186, 125, 0);
  }
  50% {
    box-shadow: 0 0 18px rgba(215, 186, 125, 0.24);
  }
  100% {
    box-shadow: 0 0 0 rgba(215, 186, 125, 0);
  }
}
</style>
