/**
 * LYRA — Electron Preload Script
 * Secure IPC bridge between the renderer process and main process.
 * Exposes a `window.lyra` API for native capabilities.
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("lyra", {
  // Platform info
  isElectron: true,
  backendPort: 8100,
  getBackendToken: () => ipcRenderer.invoke("get-backend-token"),
  onBackendStatus: callback => { const handler = (_, status) => callback(status); ipcRenderer.on("backend-status", handler); return () => ipcRenderer.removeListener("backend-status", handler); },
  getPlatformInfo: () => ipcRenderer.invoke("get-platform-info"),

  // Native notifications
  showNotification: (title, body) =>
    ipcRenderer.invoke("show-notification", { title, body }),

  // Window controls (for frameless window)
  minimize: () => ipcRenderer.invoke("window-minimize"),
  maximize: () => ipcRenderer.invoke("window-maximize"),
  close: () => ipcRenderer.invoke("window-close"),
  setWindowMode: (mode) => ipcRenderer.invoke("set-window-mode", mode),
  getWindowMode: () => ipcRenderer.invoke("get-window-mode"),

  // Native macOS Integration
  openInEditor: (filePath, line) => ipcRenderer.invoke("open-in-editor", { filePath, line }),
  getActiveApp: () => ipcRenderer.invoke("get-active-app"),

  // Native macOS Speech
  speak: (text, voice, rate) => ipcRenderer.invoke("native:speak", { text, voice, rate }),
  stopSpeaking: () => ipcRenderer.invoke("native:stop-speak"),

  // Listen for main process events
  onActivateDesktopMode: (callback) => {
    ipcRenderer.on("activate-desktop-mode", callback);
    return () => ipcRenderer.removeListener("activate-desktop-mode", callback);
  },
  onWindowModeChanged: (callback) => {
    ipcRenderer.on("window-mode-changed", (_, mode) => callback(mode));
    return () => ipcRenderer.removeListener("window-mode-changed", callback);
  },
  onToggleHUD: (callback) => {
    ipcRenderer.on("toggle-hud", callback);
    return () => ipcRenderer.removeListener("toggle-hud", callback);
  },

});
