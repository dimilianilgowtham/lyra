import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../../src/modules/MemoryManager.js", import.meta.url), "utf8");

// A browser storage fixture with transaction completion and asynchronous reads.
// Existing records are seeded before initialization, matching an upgraded app.
function browserStorage(records) {
  const conversations = new Map(records.map(record => [record.id, structuredClone(record)]));
  const storage = new Map();
  const objectStore = transaction => ({
    put(record) {
      conversations.set(record.id, structuredClone(record));
      queueMicrotask(() => transaction.oncomplete?.());
    },
    get(id) {
      const request = {};
      queueMicrotask(() => {
        request.result = structuredClone(conversations.get(id));
        request.onsuccess?.();
      });
      return request;
    },
    getAll() {
      const request = {};
      queueMicrotask(() => {
        request.result = structuredClone([...conversations.values()]);
        request.onsuccess?.();
      });
      return request;
    },
    delete(id) {
      conversations.delete(id);
      queueMicrotask(() => transaction.oncomplete?.());
    },
    clear() {
      conversations.clear();
      queueMicrotask(() => transaction.oncomplete?.());
    },
  });
  return {
    indexedDB: {
      open(name, version) {
        assert.equal(name, "lyra-memory");
        assert.equal(version, 2);
        const request = {};
        queueMicrotask(() => request.onsuccess?.({ target: { result: {
          transaction(storeName) {
            assert.equal(storeName, "conversations");
            const transaction = {};
            transaction.objectStore = () => objectStore(transaction);
            return transaction;
          },
        } } }));
        return request;
      },
    },
    localStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: key => storage.delete(key),
    },
  };
}

async function loadManager(records = [], saved = {}, backend = {}) {
  const requests = [];
  let cloudClients = 0;
  const browser = browserStorage(records);
  if (saved.preferences) browser.localStorage.setItem("lyra-prefs", JSON.stringify(saved.preferences));
  if (saved.interactions) browser.localStorage.setItem("lyra-interactions", JSON.stringify(saved.interactions));
  const context = vm.createContext({
    ...browser,
    backendClient: { listConversations: async () => ({ conversations: [] }), importConversation: async () => ({ success: true }), getConversationMessages: async () => { throw new Error("offline"); }, deleteConversation: async () => ({ success: true }), ...backend },
    console,
    AbortSignal,
    createClient() {
      cloudClients += 1;
      return { auth: { getUser: async () => ({ data: { user: null } }) } };
    },
    fetch: async (...args) => {
      requests.push(args);
      return { ok: true };
    },
    environment: { VITE_ODYSSEUS_URL: "https://unused-sync.example", VITE_SUPABASE_URL: "https://unused-cloud.example" },
  });
  vm.runInContext(source
    .replace(/^import .*BackendClient.*;$/m, "")
    .replace(/^import .*@supabase\/supabase-js.*;$/m, "")
    .replaceAll("import.meta.env", "environment")
    .replace("export const memoryManager", "globalThis.memoryManager")
    .replace("export default memoryManager;", ""), context);
  await context.memoryManager._ready();
  return { manager: context.memoryManager, requests, cloudClients, ...browser };
}

test("initialization and conversation saves only use local storage", async () => {
  const { manager, requests, cloudClients } = await loadManager();
  await manager.saveConversation({ id: "local", title: "Local chat", messages: [{ role: "user", content: "Keep this" }] });

  assert.equal(cloudClients, 0);
  assert.equal(requests.length, 0);
  assert.equal((await manager.getConversation("local")).messages[0].content, "Keep this");
});

test("existing conversations, preferences and analytics survive initialization", async () => {
  const existing = { id: "existing", title: "Saved chat", mode: "chat", messages: [{ content: "Original message" }], createdAt: 1, updatedAt: 2 };
  const { manager } = await loadManager([existing], {
    preferences: { preferredMode: "voice", theme: "dark", customPreference: "preserve" },
    interactions: [{ type: "prompt", data: { text: "Existing prompt" }, timestamp: 1 }],
  });

  manager.setPreference("sidebarOpen", false);
  manager.recordInteraction("prompt", { text: "Existing prompt" });
  await manager.saveConversation({ id: "new", title: "New chat", messages: [{ content: "New message" }] });

  assert.equal((await manager.getConversation("existing")).messages[0].content, "Original message");
  assert.equal((await manager.getConversations()).length, 2);
  assert.equal(manager.getPreferences().customPreference, "preserve");
  assert.equal(manager.getPreferences().preferredMode, "voice");
  assert.equal(manager.getPreferences().sidebarOpen, false);
  assert.equal(manager.getFrequentPrompts()[0], "Existing prompt");
  const exported = await manager.exportData();
  assert.equal(exported.conversations.length, 2);
  assert.equal(exported.preferences.customPreference, "preserve");
  assert.equal((await manager.getStats()).totalMessages, 2);
});

test("the analytics response retains the legacy sync status field", async () => {
  const { manager } = await loadManager();

  assert.equal((await manager.getStats()).odysseusSync, false);
});


test("failed migration preserves local messages and retries until server import succeeds", async () => {
  let imports = 0;
  const existing = { id: "legacy", title: "Old chat", messages: [{ role: "user", content: "Keep me" }], updatedAt: 2 };
  const { manager, localStorage } = await loadManager([existing], {}, {
    importConversation: async record => { imports++; assert.equal(record.messages[0].content, "Keep me"); if (imports === 1) throw new Error("offline"); return { success: true }; },
  });
  const first = await manager.getConversations();
  assert.equal(first[0].messages[0].content, "Keep me");
  assert.equal(localStorage.getItem("lyra-server-import:legacy"), null);
  await manager.getConversations();
  assert.equal(imports, 2);
  assert(localStorage.getItem("lyra-server-import:legacy"));
  await manager.getConversations();
  assert.equal(imports, 2);
});

test("server history replaces cached history while offline reads preserve the cache", async () => {
  let online = true;
  const { manager } = await loadManager([{ id: "saved", title: "Cache", messages: [{ role: "user", content: "Old" }], updatedAt: 1 }], {}, {
    listConversations: async () => { if (!online) throw new Error("offline"); return { conversations: [{ id: "saved", title: "Server", metadata: { mode: "analyze" } }] }; },
    getConversationMessages: async () => { if (!online) throw new Error("offline"); return { messages: [{ role: "user", content: "Actual server message" }] }; },
  });
  assert.equal((await manager.getConversations())[0].title, "Server");
  const record = await manager.getConversation("saved");
  assert.equal(record.messages[0].content, "Actual server message");
  online = false;
  assert.equal((await manager.getConversation("saved")).messages[0].content, "Actual server message");
});
