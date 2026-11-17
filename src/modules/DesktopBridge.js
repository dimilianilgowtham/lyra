/**
 * LYRA — Desktop Bridge v2.0 (Conversational Core & Safe Execution)
 * 
 * WebSocket client connecting Lyra's frontend to the authoritative
 * Python FastAPI backend (:8100) for real-time conversation, streaming,
 * interruption, memory vault, and desktop tool control.
 */

import { backendClient } from "./BackendClient";
const RECONNECT_BASE_MS = 2000;
const MAX_RECONNECT_MS = 30000;
const HEARTBEAT_MS = 25000;

class DesktopBridgeClient {
  constructor() {
    this.ws = null;
    this.connected = false;
    this.reconnectAttempts = 0;
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
    this.listeners = new Map();
    this.pendingRequests = new Map();
    this.requestId = 0;
    this._onStatusChange = null;

    // Active session tracking
    this.activeConversationId = null;
    this.userId = "default_user";
  }

  // ── Session Management ─────────────────────────────────────────

  setConversation(conversationId) {
    this.activeConversationId = conversationId;
    this._send("set_conversation", { content: conversationId });
  }

  getConversationId() {
    return this.activeConversationId;
  }

  setUserId(userId) {
    this.userId = "default_user";
  }

  // ── Connection Management ──────────────────────────────────────

  async connect() {
    if (this._connecting || (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING))) {
      return;
    }

    this._connecting = true; this._manualDisconnect = false;
    try {
      const url = await backendClient.websocketUrl();
      if (this._manualDisconnect) return;
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        console.log("[DesktopBridge] ✅ Connected to LYRA backend");
        this.connected = true;
        this.reconnectAttempts = 0;
        this._notifyStatus("connected");
        this._startHeartbeat();
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this._handleMessage(data);
        } catch (e) {
          console.warn("[DesktopBridge] Invalid message:", e);
        }
      };

      this.ws.onclose = (event) => {
        console.log("[DesktopBridge] 🔌 Disconnected:", event.code);
        this.connected = false;
        this._stopHeartbeat();
        this._notifyStatus("disconnected");
        if (!this._manualDisconnect) this._scheduleReconnect();
      };

      this.ws.onerror = (error) => {
        console.error("[DesktopBridge] ❌ Error:", error);
        this._notifyStatus("error");
      };

    } catch (e) {
      console.error("[DesktopBridge] Failed to connect:", e);
      this._notifyStatus("error");
      if (!this._manualDisconnect) this._scheduleReconnect();
    } finally { this._connecting = false; }
  }

  disconnect() {
    this._manualDisconnect = true;
    clearTimeout(this.reconnectTimer);
    this._stopHeartbeat();
    if (this.ws) {
      this.ws.close(1000, "Client disconnect");
      this.ws = null;
    }
    this.connected = false;
    this._notifyStatus("disconnected");
  }

  isConnected() {
    return this.connected && this.ws?.readyState === WebSocket.OPEN;
  }

  onStatusChange(callback) {
    this._onStatusChange = callback;
  }

  _notifyStatus(status) {
    if (this._onStatusChange) this._onStatusChange(status);
    this._emit("connection_status", { status });
  }

  _scheduleReconnect() {
    const delay = Math.min(RECONNECT_BASE_MS * Math.pow(2, this.reconnectAttempts), MAX_RECONNECT_MS);
    this.reconnectAttempts++;
    console.log(`[DesktopBridge] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  _startHeartbeat() {
    this.heartbeatTimer = setInterval(() => {
      if (this.isConnected()) {
        this._send("ping", {});
      }
    }, HEARTBEAT_MS);
  }

  _stopHeartbeat() {
    clearInterval(this.heartbeatTimer);
  }

  // ── Message Handling ───────────────────────────────────────────

  _send(type, payload) {
    if (!this.isConnected()) {
      console.warn("[DesktopBridge] Not connected, cannot send:", type);
      return false;
    }
    this.ws.send(JSON.stringify({ type, ...payload }));
    return true;
  }

  _handleMessage(data) {
    const { type } = data;

    // Track active conversation ID from backend greetings or responses
    if (data.conversation_id) {
      this.activeConversationId = data.conversation_id;
    }

    // Resolve pending request promises
    if (data.requestId && this.pendingRequests.has(data.requestId)) {
      const { resolve } = this.pendingRequests.get(data.requestId);
      this.pendingRequests.delete(data.requestId);
      resolve(data);
      return;
    }

    // Emit to registered listeners
    this._emit(type, data);
  }

  // ── Event System ───────────────────────────────────────────────

  on(event, callback) {
    if (!this.listeners.has(event)) this.listeners.set(event, []);
    this.listeners.get(event).push(callback);
    return () => {
      const cbs = this.listeners.get(event);
      if (cbs) this.listeners.set(event, cbs.filter(cb => cb !== callback));
    };
  }

  _emit(event, data) {
    const cbs = this.listeners.get(event) || [];
    cbs.forEach(cb => {
      try { cb(data); } catch (e) { console.error("[DesktopBridge] Listener error:", e); }
    });
    const wildcards = this.listeners.get("*") || [];
    wildcards.forEach(cb => {
      try { cb({ event, ...data }); } catch (e) { /* ignore */ }
    });
  }

  // ── Conversational & Voice Commands ─────────────────────────────

  /**
   * Send a text command through LYRA with unified conversation session.
   */
  sendCommand(text, options = {}) {
    return this._send("command", {
      content: text,
      message: text,
      conversation_id: this.activeConversationId,
      user_id: this.userId,
      ...options,
    });
  }

  /**
   * Send a voice-transcribed command through LYRA with unified conversation session.
   */
  sendVoiceCommand(text, options = {}) {
    return this._send("voice_command", {
      content: text,
      message: text,
      conversation_id: this.activeConversationId,
      user_id: this.userId,
      ...options,
    });
  }

  /**
   * Interrupt the assistant: halts generation task and stops speech output.
   */
  interrupt() {
    console.log("[DesktopBridge] 🛑 Sending interrupt signal");
    return this._send("interrupt", {});
  }

  // ── Memory Vault API ────────────────────────────────────────────

  async getMemories() { const data = await backendClient.request("/api/memories?user_id=default_user"); return data.memories || []; }
  addMemory(fact, category = "preference", consented = true) { return backendClient.request("/api/memories", { method: "POST", body: { user_id: "default_user", fact, category, consented } }); }
  updateMemory(id, updates = {}) { return backendClient.request(`/api/memories/${encodeURIComponent(id)}`, { method: "PUT", body: updates }); }
  deleteMemory(id) { return backendClient.request(`/api/memories/${encodeURIComponent(id)}`, { method: "DELETE" }); }
  clearMemories() { return backendClient.request("/api/memories?user_id=default_user", { method: "DELETE" }); }
  async getAuditLog(limit = 50) { const data = await backendClient.request(`/api/audit-log?limit=${limit}`); return data.logs || []; }
  openApp(appName) { return this.sendCommand(`open ${appName}`); }
  getSystemStats() { return backendClient.request("/api/system/stats"); }
  async getAvailableApps() { const data = await backendClient.request("/api/apps"); return data.apps || []; }
  healthCheck() { return backendClient.health(); }
  sendRAGQuery(query, sources = ["local", "git"]) { return this._send("rag_query", { content: query, message: query, sources, conversation_id: this.activeConversationId }); }
  ragSearch(query, sources = ["local", "git"], basePath) { return backendClient.request("/api/rag", { method: "POST", body: { query, sources, ...(basePath ? { base_path: basePath } : {}) } }); }
  speakDirect(text, voice = null, rate = null) { return backendClient.request("/api/voice/speak", { method: "POST", body: { text, voice, rate } }); }
  stopSpeech() { return backendClient.request("/api/voice/stop", { method: "POST" }); }

}

export const DesktopBridge = new DesktopBridgeClient();
export default DesktopBridge;
