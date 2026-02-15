<script setup lang="ts">
import { computed } from 'vue';
import { useRuntimeStore } from '../stores/runtime';
import HumanChatThread from './HumanChatThread.vue';

const props = defineProps<{
  sessionId: string;
}>();

const runtime = useRuntimeStore();

const pending = computed(() => runtime.humanPendingCount(props.sessionId));
</script>

<template>
  <div class="root">
    <div class="top">
      <div class="title">Human</div>
      <div class="status" :class="{ pending: pending > 0 }">
        {{ pending > 0 ? `Waiting for reply (${pending})` : 'No pending requests' }}
      </div>
    </div>

    <HumanChatThread :session-id="sessionId" />
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

.top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
}

.title {
  font-weight: 700;
}

.status {
  font-size: 12px;
  opacity: 0.85;
}

.status.pending {
  color: var(--vscode-notificationsWarningIcon-foreground, #d7ba7d);
}
</style>
