/**
 * LYRA — Electron Main Process
 * Native macOS desktop shell for the LYRA AI assistant.
 * Features: frameless window, system tray, global shortcuts, auto-start backend.
 */

const { app, BrowserWindow, Tray, Menu, globalShortcut, nativeImage, ipcMain, shell, session, systemPreferences, dialog } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const fs = require("fs");
const crypto = require("crypto");
const { BackendManager } = require("./electron/backend-manager.cjs");
const { runtimePaths } = require("./electron/runtime-paths.cjs");
app.setName("Lyra");
app.setPath("userData", path.join(app.getPath("appData"), "Lyra"));
const hasInstanceLock = app.requestSingleInstanceLock();
const runtime = runtimePaths({ packaged: app.isPackaged, appDir: __dirname, resourcesPath: process.resourcesPath, userData: app.getPath("userData") });
const backendTokenPath = runtime.tokenPath;
fs.mkdirSync(path.dirname(backendTokenPath), { recursive: true });
if (fs.existsSync(backendTokenPath) && fs.lstatSync(backendTokenPath).isSymbolicLink()) throw new Error("Backend credential must not be a symbolic link.");
let backendToken = process.env.BACKEND_AUTH_TOKEN || (fs.existsSync(backendTokenPath) ? fs.readFileSync(backendTokenPath, "utf8").trim() : "");
if (backendToken.length < 32) { backendToken = crypto.randomBytes(32).toString("base64url"); fs.writeFileSync(backendTokenPath, backendToken, { mode: 0o600 }); }
if (fs.existsSync(backendTokenPath)) fs.chmodSync(backendTokenPath, 0o600);
fs.mkdirSync(path.dirname(runtime.logPath), { recursive: true });
function backendLog(message) {
  try {
    if (fs.existsSync(runtime.logPath) && fs.statSync(runtime.logPath).size > 5 * 1024 * 1024) fs.renameSync(runtime.logPath, runtime.logPath + '.previous');
    fs.appendFileSync(runtime.logPath, new Date().toISOString() + ' ' + message + '\n', {mode:0o600});
    fs.chmodSync(runtime.logPath, 0o600);
  } catch (error) { console.error('[Lyra] Could not write backend log:', error.message); }
}
let backendStatus = {state:'stopped',owned:false};
const backendManager = new BackendManager({ ...runtime, authToken:backendToken, log:backendLog, onStatus:status => {
  backendStatus = status;
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('backend-status', status);
}});

let mainWindow = null;
let tray = null;

app.setName("Lyra");
// Ensure audio playback is never blocked by autoplay policy
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");

const FRONTEND_URL = "http://127.0.0.1:3000";
const BACKEND_PORT = 8100;

// ── Window Creation ───────────────────────────────────────────────

function loadAppContent(window) {
  const distHtml = path.join(__dirname, "dist", "index.html");
  const fs = require("fs");
  const http = require("http");

  if (app.isPackaged) return _loadDist(window, distHtml);

  // Only development launches may use a development server.
  const req = http.get(FRONTEND_URL, (res) => {
    if (res.statusCode >= 200 && res.statusCode < 400) {
      console.log("[Electron] Dev server detected on http://localhost:3000. Loading live dev URL.");
      window.loadURL(FRONTEND_URL);
    } else {
      _loadDist(window, distHtml);
    }
  });

  req.on("error", () => {
    console.log("[Electron] No dev server running. Loading standalone local dist/index.html directly.");
    _loadDist(window, distHtml);
  });

  req.setTimeout(800, () => {
    req.destroy();
    _loadDist(window, distHtml);
  });
}

function _loadDist(window, distHtml) {
  const fs = require("fs");
  if (fs.existsSync(distHtml)) {
    window.loadFile(distHtml);
  } else {
    dialog.showErrorBox("Lyra interface is missing", "Rebuild or reinstall Lyra. The installed app must include its built interface.");
    app.quit();
  }
}

let currentWindowMode = "desktop";

function findEditorBinary() {
  const fs = require("fs");
  const cursorBin = "/Applications/Cursor.app/Contents/Resources/app/bin/cursor";
  const codeBin = "/Applications/Visual Studio Code 2.app/Contents/Resources/app/bin/code";
  const standardCodeBin = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code";
  if (fs.existsSync(cursorBin)) return { bin: cursorBin, name: "Cursor" };
  if (fs.existsSync(codeBin)) return { bin: codeBin, name: "VS Code" };
  if (fs.existsSync(standardCodeBin)) return { bin: standardCodeBin, name: "VS Code" };
  return null;
}

function applyWindowMode(mode) {
  if (!mainWindow) return;
  const { screen } = require("electron");
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width: screenWidth, height: screenHeight } = primaryDisplay.workAreaSize;

  if (mode === "hud") {
    currentWindowMode = "hud";
    mainWindow.setAlwaysOnTop(true, "floating");
    if (process.platform === "darwin") {
      try {
        mainWindow.setVibrancy("under-window");
        app.dock?.show();
      } catch (e) {}
    }
    const hudWidth = 860;
    const hudHeight = 620;
    const x = Math.round(screenWidth - hudWidth - 40);
    const y = Math.round(40);
    mainWindow.setBounds({ x, y, width: hudWidth, height: hudHeight }, true);
    mainWindow.webContents.send("window-mode-changed", "hud");
  } else {
    currentWindowMode = "deck";
    mainWindow.setAlwaysOnTop(false);
    if (process.platform === "darwin") {
      try {
        mainWindow.setVibrancy(null);
        mainWindow.setVisibleOnAllWorkspaces(false);
      } catch (e) {}
    }
    const deckWidth = Math.min(1400, screenWidth - 60);
    const deckHeight = Math.min(900, screenHeight - 60);
    mainWindow.setBounds({
      x: Math.round((screenWidth - deckWidth) / 2),
      y: Math.round((screenHeight - deckHeight) / 2),
      width: deckWidth,
      height: deckHeight,
    }, true);
    mainWindow.webContents.send("window-mode-changed", "deck");
  }
}

function createWindow() {
  const appIcon = path.join(__dirname, "public", "lyra_logo.png");
  const { screen } = require("electron");
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width: screenWidth, height: screenHeight } = primaryDisplay.workAreaSize;
  const hudWidth = Math.min(1440, screenWidth - 80);
  const hudHeight = Math.min(960, screenHeight - 80);

  mainWindow = new BrowserWindow({
    title: "Lyra",
    width: hudWidth,
    height: hudHeight,
    center: true,
    minWidth: 680,
    minHeight: 440,
    frame: false,
    transparent: false,
    visualEffectState: "active",
    alwaysOnTop: false,
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 15, y: 15 },
    backgroundColor: "#11130f",
    icon: appIcon,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: true,
    },
  });

  if (process.platform === "darwin") {
    try {
      app.dock?.show();
    } catch (e) {}
  }

  // Set macOS dock icon
  if (process.platform === "darwin" && app.dock) {
    try {
      app.dock.setIcon(appIcon);
    } catch (e) {
      console.warn("[Electron] Could not set dock icon:", e.message);
    }
  }

  // Load the app content (Vite if running, else direct dist/index.html)
  loadAppContent(mainWindow);

  // Show window when ready (prevents flash of white)
  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    mainWindow.focus();
  });

  // Strict standalone desktop mode: prevent opening external websites
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    console.log("[Electron] Blocked external navigation (pure desktop mode):", url);
    return { action: "deny" };
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  // Prevent full close — hide to tray instead
  mainWindow.on("close", (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });
}

// ── System Tray ─────────────────────────────────────────────────

function createTray() {
  // Use LYRA logo for tray icon
  const logoPath = path.join(__dirname, "public", "lyra_logo.png");
  const fallbackPath = path.join(__dirname, "public", "favicon.svg");
  const iconPath = require("fs").existsSync(logoPath) ? logoPath : fallbackPath;
  let trayIcon;
  try {
    trayIcon = nativeImage.createFromPath(iconPath).resize({ width: 18, height: 18 });
  } catch {
    trayIcon = nativeImage.createEmpty();
  }

  tray = new Tray(trayIcon);
  tray.setToolTip("LYRA AI Assistant");

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Show LYRA",
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    { type: "separator" },
    {
      label: "Desktop Mode",
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
          mainWindow.webContents.send("activate-desktop-mode");
        }
      },
    },
    { type: "separator" },
    {
      label: "Quit LYRA",
      click: () => {
        app.isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);

  // Click tray icon to toggle window
  tray.on("click", () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.hide();
      } else {
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });
}

// ── Backend Management ──────────────────────────────────────────

function startBackend() { return backendManager.start(); }
function waitForBackend() { return backendManager.waitForReady(); }
function stopBackend() { return backendManager.stop(); }

// ── IPC Handlers ────────────────────────────────────────────────

function setupIPC() {
  ipcMain.handle("get-platform-info", () => ({
    platform: process.platform,
    arch: process.arch,
    isElectron: true,
    version: app.getVersion(),
  }));

  ipcMain.handle("show-notification", (_, { title, body }) => {
    const { Notification } = require("electron");
    if (Notification.isSupported()) {
      new Notification({ title, body }).show();
      return true;
    }
    return false;
  });

  ipcMain.handle("window-minimize", () => mainWindow?.minimize());
  ipcMain.handle("window-maximize", () => {
    if (mainWindow?.isMaximized()) {
      mainWindow.unmaximize();
    } else {
      mainWindow?.maximize();
    }
  });
  ipcMain.handle("window-close", () => mainWindow?.hide());

  // Window Mode & HUD Control
  ipcMain.handle("set-window-mode", (_, mode) => {
    applyWindowMode(mode);
    return currentWindowMode;
  });

  ipcMain.handle("get-window-mode", () => currentWindowMode);

  // Native macOS Editor Deep-Linking
  ipcMain.handle("open-in-editor", async (_, { filePath, line }) => {
    const editor = findEditorBinary();
    const target = line ? `${filePath}:${line}` : filePath;
    if (editor) {
      const { spawn } = require("child_process");
const fs = require("fs");
const crypto = require("crypto");
const backendTokenPath = path.join(__dirname, "lyra-backend", "data", ".backend-auth-token");
fs.mkdirSync(path.dirname(backendTokenPath), { recursive: true });
if (fs.existsSync(backendTokenPath) && fs.lstatSync(backendTokenPath).isSymbolicLink()) throw new Error("Backend credential must not be a symbolic link.");
let backendToken = process.env.BACKEND_AUTH_TOKEN || (fs.existsSync(backendTokenPath) ? fs.readFileSync(backendTokenPath, "utf8").trim() : "");
if (backendToken.length < 32) { backendToken = crypto.randomBytes(32).toString("base64url"); fs.writeFileSync(backendTokenPath, backendToken, { mode: 0o600 }); }
if (fs.existsSync(backendTokenPath)) fs.chmodSync(backendTokenPath, 0o600);
      spawn(editor.bin, ["-g", target], { detached: true, stdio: "ignore" });
      return { success: true, editor: editor.name, target };
    } else {
      shell.openPath(filePath);
      return { success: true, editor: "System Default", target };
    }
  });

  // macOS Active App Detection
  ipcMain.handle("get-active-app", async () => {
    return new Promise((resolve) => {
      const { exec } = require("child_process");
      exec(
        `osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true'`,
        { timeout: 2000 },
        (err, stdout) => {
          if (err) return resolve({ name: "Unknown", error: err.message });
          resolve({ name: stdout.trim() });
        }
      );
    });
  });

  // ── Native macOS Text-to-Speech (Zero-latency native say) ──────
  ipcMain.handle("native:speak", async (_, { text, voice, rate }) => {
    return new Promise((resolve) => {
      const v = voice || "Samantha";
      const r = rate || 185;
      const clean = (text || "")
        .replace(/https?:\/\/\S+/g, "")
        .replace(/[*_#`~[\]()]/g, "")
        .replace(/["\\]/g, "")
        .trim();
      if (!clean) return resolve(false);

      const proc = spawn("say", ["-v", v, "-r", String(r), clean]);
      proc.on("close", (code) => resolve(code === 0));
      proc.on("error", (err) => {
        console.warn("[Electron] native:speak error:", err);
        resolve(false);
      });
    });
  });

  ipcMain.handle("native:stop-speak", () => {
    const { exec } = require("child_process");
    exec("killall say", () => {});
    return true;
  });

  // Renderer code receives a local service capability, never provider keys or a
  // direct shell/filesystem bridge. Every tool goes through durable task approval.
  ipcMain.handle("get-backend-token", event => {
    if (!mainWindow || event.sender !== mainWindow.webContents || event.senderFrame !== mainWindow.webContents.mainFrame) {
      throw new Error("Only the assistant window may access its local session.");
    }
    const source = event.senderFrame.url;
    if (!source.startsWith("file://") && !source.startsWith(FRONTEND_URL + "/")) {
      throw new Error("Untrusted renderer origin.");
    }
    return backendToken;
  });

}

// ── App Lifecycle ───────────────────────────────────────────────

if (!hasInstanceLock) { app.quit(); } else app.whenReady().then(() => {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {label:"Lyra",submenu:[{role:"about"},{type:"separator"},{role:"hide"},{role:"hideOthers"},{type:"separator"},{role:"quit"}]},
    {label:"Edit",submenu:[{role:"undo"},{role:"redo"},{type:"separator"},{role:"cut"},{role:"copy"},{role:"paste"},{role:"selectAll"}]},
    {label:"View",submenu:[{role:"reload"},{role:"resetZoom"},{role:"zoomIn"},{role:"zoomOut"},{role:"togglefullscreen"}]},
    {label:"Window",submenu:[{role:"minimize"},{role:"zoom"},{role:"front"}]}
  ]));
  // macOS explicit microphone access request
  if (process.platform === "darwin" && systemPreferences.askForMediaAccess) {
    systemPreferences.askForMediaAccess("microphone").then((granted) => {
      console.log(`[Electron] macOS microphone access: ${granted ? "GRANTED" : "DENIED"}`);
    }).catch((err) => {
      console.warn("[Electron] Error requesting microphone access:", err.message);
    });
  }

  // Grant media (microphone/audio) permission to Electron window session
  session.defaultSession.setPermissionCheckHandler((webContents, permission) => {
    if (permission === "media") return true;
    return false;
  });

  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    if (permission === "media") {
      return callback(true);
    }
    callback(false);
  });

  // Register global shortcuts: Cmd+Shift+Space (HUD toggle) and Cmd+Shift+L (legacy toggle)
  const toggleLyraWindow = (targetMode) => {
    if (mainWindow) {
      if (mainWindow.isVisible() && mainWindow.isFocused()) {
        mainWindow.hide();
      } else {
        if (targetMode && targetMode !== currentWindowMode) {
          applyWindowMode(targetMode);
        }
        mainWindow.show();
        mainWindow.focus();
        mainWindow.webContents.send("toggle-hud");
      }
    }
  };

  globalShortcut.register("CommandOrControl+Shift+Space", () => {
    toggleLyraWindow("hud");
  });

  globalShortcut.register("CommandOrControl+Shift+L", () => {
    toggleLyraWindow();
  });

  setupIPC();
  // Start and verify the owned service before showing the main window.
  startBackend()
    .then(() => {
      createWindow();
      createTray();
    })
    .catch((err) => {
      console.error("[Electron] Backend failed to start:", err.message);
      createWindow();
      createTray();
      dialog.showMessageBox(mainWindow, {type:"error",title:"Lyra could not start its backend",message:err.message,detail:"See the backend log for details. Your saved data is retained.",buttons:["Retry","Open log","Close"],defaultId:0}).then(async ({response}) => {
        if (response === 0) { try { await startBackend(); } catch (retryError) { dialog.showErrorBox("Lyra backend", retryError.message); } }
        if (response === 1) shell.openPath(runtime.logPath);
      });
    });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    } else if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
});

app.on("window-all-closed", () => {
  // On macOS, keep app running in tray
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
});

let shutdownComplete = false;
app.on("before-quit", event => {
  app.isQuitting = true;
  if (!shutdownComplete) {
    event.preventDefault();
    stopBackend().finally(() => { shutdownComplete = true; app.quit(); });
  }
});
app.on('second-instance', () => { if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.show(); mainWindow.focus(); } });
