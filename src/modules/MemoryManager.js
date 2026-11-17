import { backendClient } from "./BackendClient";
/**
 * LYRA — Local Memory Manager
 *
 * IndexedDB keeps browser chat history. localStorage keeps lightweight UI
 * preferences and interaction analytics. Backend personal memory is managed
 * separately by the local backend's SQLite database.
 */

const DB_NAME = "lyra-memory";
const DB_VERSION = 2;
const STORE_CONVERSATIONS = "conversations";
const PREFS_KEY = "lyra-prefs";

class MemoryManager {
  constructor() {
    this.db = null;
    this._dbReady = this._initDB();
    this._dbReady.catch(() => {});
    this.lastError = "";
    this.serverRecords = new Map();
  }

  // ── IndexedDB Setup ───────────────────────────────────────────────────────

  _initDB() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);

      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        if (!db.objectStoreNames.contains(STORE_CONVERSATIONS)) {
          const store = db.createObjectStore(STORE_CONVERSATIONS, { keyPath: "id" });
          store.createIndex("updatedAt", "updatedAt", { unique: false });
          store.createIndex("mode", "mode", { unique: false });
        }
      };

      request.onsuccess = (event) => {
        this.db = event.target.result;
        resolve(this.db);
      };

      request.onerror = (event) => {
        console.error("Lyra Memory: IndexedDB failed:", event.target.error);
        reject(event.target.error);
      };
    });
  }

  async _ready() {
    if (this.db) return this.db;
    return this._dbReady;
  }

  // ── Conversation Storage ──────────────────────────────────────────────────

  async saveConversation(conversation) {
    try {
      const db = await this._ready();
      const record = {
        ...conversation,
        id: conversation.id || `conv_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        title: (conversation.title || "Untitled").slice(0, 200),
        mode: conversation.mode || "chat",
        messages: conversation.messages || [],
        updatedAt: Date.now(),
        createdAt: conversation.createdAt || Date.now(),
      };

      const tx = db.transaction(STORE_CONVERSATIONS, "readwrite");
      tx.objectStore(STORE_CONVERSATIONS).put(record);
      await new Promise((resolve, reject) => {
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error);
      });

      return record.id;
    } catch (e) {
      console.warn("Lyra Memory: save failed:", e.message);
      return null;
    }
  }

  async _getLocalConversations() {
    try {
      const db = await this._ready();
      const tx = db.transaction(STORE_CONVERSATIONS, "readonly");
      const store = tx.objectStore(STORE_CONVERSATIONS);

      return new Promise((resolve) => {
        const request = store.getAll();
        request.onsuccess = () => {
          const convos = request.result || [];
          convos.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
          resolve(convos);
        };
        request.onerror = () => resolve([]);
      });
    } catch {
      return [];
    }
  }

  async _getLocalConversation(id) {
    try {
      const db = await this._ready();
      const tx = db.transaction(STORE_CONVERSATIONS, "readonly");
      return new Promise((resolve) => {
        const request = tx.objectStore(STORE_CONVERSATIONS).get(id);
        request.onsuccess = () => resolve(request.result || null);
        request.onerror = () => resolve(null);
      });
    } catch {
      return null;
    }
  }

  async _deleteLocalConversation(id) {
    try {
      const db = await this._ready();
      const tx = db.transaction(STORE_CONVERSATIONS, "readwrite");
      tx.objectStore(STORE_CONVERSATIONS).delete(id);
      await new Promise((resolve) => { tx.oncomplete = resolve; });
    } catch (e) {
      console.warn("Lyra Memory: delete failed:", e.message);
    }
  }

  async searchConversations(query) {
    if (!query?.trim()) return this.getConversations();
    const all = await this.getConversations();
    const q = query.toLowerCase();
    return all.filter(c =>
      (c.title || "").toLowerCase().includes(q) ||
      (c.messages || []).some(m => (m.content || "").toLowerCase().includes(q))
    );
  }

  _normalize(record) {
    let metadata = record.metadata || {};
    try { if (record.metadata_json) metadata = JSON.parse(record.metadata_json); } catch {}
    return { ...record, mode: record.mode || metadata.mode || "chat", createdAt: record.createdAt || Date.parse(record.created_at) || Date.now(), updatedAt: record.updatedAt || Date.parse(record.updated_at) || Date.now() };
  }

  async migrateConversations() {
    const records = await this._getLocalConversations();
    for (const record of records) {
      if (record.serverCached) continue;
      const marker = `lyra-server-import:${record.id}`;
      const version = String(record.updatedAt || 0);
      if (localStorage.getItem(marker) === version) continue;
      try {
        const result = await backendClient.importConversation(record);
        if (result.success === false) throw new Error(result.error || "Conversation import failed");
        localStorage.setItem(marker, version);
      } catch (error) { this.lastError = error.message; }
    }
    return records;
  }

  async getConversations() {
    const local = await this.migrateConversations();
    try {
      const data = await backendClient.listConversations();
      const server = (data.conversations || []).map(record => this._normalize(record));
      server.forEach(record => this.serverRecords.set(record.id, record));
      this.lastError = "";
      return [...server, ...local.filter(record => !server.some(item => item.id === record.id))].sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    } catch (error) { this.lastError = error.message; return local; }
  }

  async getConversation(id) {
    const local = await this._getLocalConversation(id);
    try {
      const data = await backendClient.getConversationMessages(id);
      const record = { ...local, ...this.serverRecords.get(id), id, messages: data.messages || [], serverCached: true };
      await this.saveConversation(record);
      this.lastError = "";
      return record;
    } catch (error) { this.lastError = error.message; return local; }
  }

  async deleteConversation(id) {
    const result = await backendClient.deleteConversation(id);
    if (result.success === false) throw new Error(result.error || "Conversation delete failed");
    await this._deleteLocalConversation(id);
    this.serverRecords.delete(id);
    localStorage.removeItem(`lyra-server-import:${id}`);
  }

  // Keep legacy local history; retention is an explicit user action.
  async cleanup() { return 0; }

  // ── Preferences (localStorage) ────────────────────────────────────────────

  getPreferences() {
    try {
      const raw = localStorage.getItem(PREFS_KEY);
      return raw ? JSON.parse(raw) : this._defaultPreferences();
    } catch {
      return this._defaultPreferences();
    }
  }

  setPreference(key, value) {
    const prefs = this.getPreferences();
    prefs[key] = value;
    prefs.lastUpdated = Date.now();
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    return prefs;
  }

  setPreferences(updates) {
    const prefs = { ...this.getPreferences(), ...updates, lastUpdated: Date.now() };
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    return prefs;
  }

  _defaultPreferences() {
    return {
      preferredMode: "chat",
      voiceLanguage: "en-US",
      voiceAutoRead: false,
      voiceAutoSend: false,
      sidebarOpen: true,
      theme: "dark",
      lastUpdated: Date.now(),
    };
  }

  // ── Interaction Analytics (localStorage) ──────────────────────────────────

  recordInteraction(type, data) {
    try {
      const key = "lyra-interactions";
      const raw = localStorage.getItem(key);
      const interactions = raw ? JSON.parse(raw) : [];
      interactions.push({ type, data, timestamp: Date.now() });
      localStorage.setItem(key, JSON.stringify(interactions.slice(-200)));
    } catch { /* ignore */ }
  }

  getFrequentPrompts(limit = 5) {
    try {
      const raw = localStorage.getItem("lyra-interactions");
      const interactions = raw ? JSON.parse(raw) : [];
      const counts = {};
      interactions
        .filter(i => i.type === "prompt")
        .forEach(i => {
          const key = i.data?.text?.slice(0, 60) || "";
          if (key) counts[key] = (counts[key] || 0) + 1;
        });
      return Object.entries(counts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, limit)
        .map(([text]) => text);
    } catch {
      return [];
    }
  }

  async getStats() {
    const convos = await this.getConversations();
    const prefs = this.getPreferences();
    const totalMessages = convos.reduce((sum, c) => sum + (c.messages?.length || 0), 0);
    return {
      conversations: convos.length,
      totalMessages,
      preferredMode: prefs.preferredMode,
      oldestConversation: convos.length > 0
        ? new Date(Math.min(...convos.map(c => c.createdAt || Date.now()))).toLocaleDateString()
        : "N/A",
      odysseusSync: false,
    };
  }

  async clearAll() {
    try {
      const db = await this._ready();
      const tx = db.transaction(STORE_CONVERSATIONS, "readwrite");
      tx.objectStore(STORE_CONVERSATIONS).clear();
      await new Promise((resolve) => { tx.oncomplete = resolve; });
    } catch { /* ignore */ }
    localStorage.removeItem(PREFS_KEY);
    localStorage.removeItem("lyra-interactions");
  }

  async exportData() {
    const convos = await this.getConversations();
    const prefs = this.getPreferences();
    return { conversations: convos, preferences: prefs, exportedAt: new Date().toISOString() };
  }
}

export const memoryManager = new MemoryManager();
export default memoryManager;
