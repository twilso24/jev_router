import { createStore } from "/js/AlpineStore.js";
import * as api from "/js/api.js";
import { toastFrontendError } from "/components/notifications/notification-store.js";
import { store as chatsStore } from "/components/sidebar/chats/chats-store.js";

const endpoint = "plugins/jev_router/routing_kill";

const model = {
  contextId: "",
  available: false,
  loading: false,
  saving: false,
  enabled: true, // per-chat switch; null-safe default on
  globalEnabled: true,
  effective: true,
  requestId: 0,

  onMount() {
    return this.refresh(chatsStore.selected || "");
  },

  cleanup() {
    this.requestId += 1;
    this.reset("");
  },

  reset(contextId) {
    this.contextId = contextId;
    this.available = false;
    this.loading = false;
    this.saving = false;
    this.enabled = true;
    this.globalEnabled = true;
    this.effective = true;
  },

  apply(data) {
    this.available = !!data?.ok;
    this.enabled = data?.enabled !== false;
    this.globalEnabled = data?.global_enabled !== false;
    this.effective = data?.effective !== false;
  },

  async refresh(contextId) {
    contextId = String(contextId || "");
    const requestId = ++this.requestId;
    if (!contextId) {
      this.reset("");
      return;
    }

    this.contextId = contextId;
    this.loading = true;
    try {
      const response = await api.callJsonApi(endpoint, {
        action: "get",
        context_id: contextId,
      });
      if (requestId === this.requestId && contextId === this.contextId)
        this.apply(response);
    } catch (error) {
      if (requestId === this.requestId) this.reset(contextId);
    } finally {
      if (requestId === this.requestId) this.loading = false;
    }
  },

  async toggle(contextId) {
    contextId = String(contextId || this.contextId || "");
    if (!contextId || this.saving || chatsStore.selectedContext?.running)
      return false;
    if (!this.globalEnabled) return false; // master switch off -> locked

    this.saving = true;
    try {
      const response = await api.callJsonApi(endpoint, {
        action: "set",
        context_id: contextId,
        enabled: !this.enabled,
      });
      if (contextId === this.contextId) this.apply(response);
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      void toastFrontendError(message, "Jev Router");
      return false;
    } finally {
      this.saving = false;
    }
  },

  label() {
    return this.effective ? "route on" : "route off";
  },

  title() {
    if (!this.globalEnabled)
      return "Jev Router disabled globally in plugin settings; per-chat switch is locked off";
    return this.effective
      ? "Jev Router routing is on for this chat; click to disable for this chat"
      : "Jev Router routing is off for this chat; click to enable for this chat";
  },
};

export const store = createStore("jevKillSwitch", model);