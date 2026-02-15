import { defineStore } from 'pinia';

export type TabId = 'preview' | 'debug' | 'run' | 'vibe';

export const useUiStore = defineStore('ui', {
  state: () => ({
    activeTab: 'preview' as TabId,
    unreadRunSessionIds: [] as string[],
    chatSessionId: null as string | null,
    chatPopupVisible: false
  }),
  actions: {
    setActiveTab(tab: TabId) {
      this.activeTab = tab;
      if (tab === 'run') {
        this.unreadRunSessionIds = [];
      }
    },
    markRunActivity(sessionId: string | null | undefined) {
      if (this.activeTab === 'run') return;
      const sid = typeof sessionId === 'string' ? sessionId : '';
      if (!sid) return;
      if (this.unreadRunSessionIds.includes(sid)) return;
      this.unreadRunSessionIds = [...this.unreadRunSessionIds, sid].slice(-99);
    },
    restoreChatState() {
      try {
        const sessionIdRaw = window.localStorage.getItem('masfactoryVisualizer.human.chatPopup.sessionId');
        const sessionId = sessionIdRaw && sessionIdRaw.trim() ? sessionIdRaw.trim() : null;
        if (sessionId) {
          this.chatSessionId = sessionId;
          const visibleRaw = window.localStorage.getItem(
            `masfactoryVisualizer.human.chatPopupVisible.${sessionId}`
          );
          if (visibleRaw === '1' || visibleRaw === 'true') this.chatPopupVisible = true;
          else if (visibleRaw === '0' || visibleRaw === 'false') this.chatPopupVisible = false;
        }
      } catch {
        // ignore
      }
    },
    openChat(sessionId: string) {
      const sid = typeof sessionId === 'string' ? sessionId.trim() : '';
      if (!sid) return;
      this.chatSessionId = sid;
      this.chatPopupVisible = true;
      try {
        window.localStorage.setItem('masfactoryVisualizer.human.chatPopup.sessionId', sid);
        window.localStorage.setItem(`masfactoryVisualizer.human.chatPopupVisible.${sid}`, '1');
      } catch {
        // ignore
      }
    },
    hideChat() {
      this.chatPopupVisible = false;
      const sid = this.chatSessionId;
      if (!sid) return;
      try {
        window.localStorage.setItem('masfactoryVisualizer.human.chatPopup.sessionId', sid);
        window.localStorage.setItem(`masfactoryVisualizer.human.chatPopupVisible.${sid}`, '0');
      } catch {
        // ignore
      }
    },
    closeChat() {
      const sid = this.chatSessionId;
      this.chatPopupVisible = false;
      this.chatSessionId = null;
      try {
        if (sid) window.localStorage.removeItem(`masfactoryVisualizer.human.chatPopupVisible.${sid}`);
        window.localStorage.removeItem('masfactoryVisualizer.human.chatPopup.sessionId');
      } catch {
        // ignore
      }
    },
    toggleChat(sessionId: string) {
      const sid = typeof sessionId === 'string' ? sessionId.trim() : '';
      if (!sid) return;
      if (this.chatPopupVisible && this.chatSessionId === sid) {
        this.hideChat();
        return;
      }
      this.openChat(sid);
    }
  }
});
