/**
 * LYRA — Enhanced Application Interface
 * Premium AI workspace with dynamic orb visualization, luxurious materials, and refined interactions
 * Builds upon the existing HUD design system with elevated aesthetics and improved spatial composition
 */

import React, { useState, useRef, useEffect, useCallback } from "react";

// Components
import ChatArea from "./components/ChatArea/ChatArea";
import InputBar from "./components/InputBar/InputBar";
import Sidebar from "./components/Sidebar/Sidebar";
import TopBar from "./components/TopBar/TopBar";
import HudPanel from "./components/HudPanel/HudPanel";
import ErrorBoundary from "./components/common/ErrorBoundary";
import KeyboardShortcuts from "./components/common/KeyboardShortcuts";
import DesktopMode from "./components/DesktopMode/DesktopMode";
import TaskPanel from "./components/Tasks/TaskPanel";

// Modules
import { backendClient } from "./modules/BackendClient";
import { ModelRegistry } from "./modules/ModelRegistry";
import { ModelRouter } from "./modules/ModelRouter";
import { memoryManager } from "./modules/MemoryManager";
import { voiceEngine } from "./modules/VoiceEngine";
import { useLyraAgent } from "./hooks/useLyraAgent";

// Utils
import { MODES, TONE_PRESETS, RESPONSE_LENGTHS, MODE_DIRECTIVES } from "./utils/constants";
import { readFileAsText, isFileSupported } from "./utils/fileProcessor";

export default function App() {
  const user = {
    id: "default_user",
    name: "Anil Gowtham",
    email: "anil.gowtham@local",
    title: "Engineer",
  };

  // ── Chat State ──────────────────────────────────────────────
  const [activeMode, setActiveMode] = useState("chat");
  const [chats, setChats] = useState([]);
  const [activeChatId, setActiveChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  // ── UI State ────────────────────────────────────────────────
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 720);
  const [speakingId, setSpeakingId] = useState(null);
  const [copied, setCopied] = useState(null);
  const [showPrompts, setShowPrompts] = useState(false);
  const [attachedFile, setAttachedFile] = useState(null);
  const [attachedFiles, setAttachedFiles] = useState([]);
  const [dragOver, setDragOver] = useState(false);
  const [lyraInfo, setLyraInfo] = useState(false);
  const [activePanel, setActivePanel] = useState("tasks");

  // ── Feature State ───────────────────────────────────────────
  const [tone, setTone] = useState("professional");
  const [responseLength, setResponseLength] = useState(RESPONSE_LENGTHS[1]);
  const [voiceLanguage, setVoiceLanguage] = useState("en-US");
  const [selectedModel, setSelectedModel] = useState(null);

  // ── Desktop Control State ───────────────────────────────────
  const [desktopModeActive, setDesktopModeActive] = useState(false);
  const [desktopInitialView, setDesktopInitialView] = useState('chat');
  const openTerminal = () => { setDesktopInitialView('terminal'); setDesktopModeActive(true); };

  // ── Agentic AI Hook ─────────────────────────────────────────
  const agent = useLyraAgent({ conversationId: activeChatId, initialMessages: messages });
  const busy = loading || agent.isThinking;
  const selectionRef = useRef(null);

  useEffect(() => { ModelRegistry.setHealth(agent.health); }, [agent.health]);
  useEffect(() => {
    if (!activeChatId || !agent.agentMessages.length) return;
    const record = {
      id: activeChatId,
      title: chats.find(chat => chat.id === activeChatId)?.title || "Conversation",
      mode: activeMode,
      messages: agent.agentMessages,
      serverCached: true
    };
    memoryManager.saveConversation(record);
    setChats(previous => previous.map(chat =>
      chat.id === activeChatId ? { ...chat, messages: agent.agentMessages } : chat
    ));
  }, [activeChatId, agent.agentMessages]);

  // ── Refs ────────────────────────────────────────────────────
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  // ── Electron Tray / Shortcut Desktop Mode Listener ──────────
  useEffect(() => {
    if (window.lyra?.onActivateDesktopMode) {
      const unsub = window.lyra.onActivateDesktopMode(() => {
        setDesktopModeActive(true);
      });
      return () => unsub?.();
    }
  }, []);

  // ── Memory ──────────────────────────────────────────────────
  useEffect(() => {
    if (!user?.id) return;
    const prefs = memoryManager.getPreferences();
    if (prefs.preferredMode) setActiveMode(MODES.some(mode => mode.id === prefs.preferredMode) ? prefs.preferredMode : "chat");
    if (prefs.voiceLanguage) setVoiceLanguage(prefs.voiceLanguage);
    if (prefs.sidebarOpen !== undefined) setSidebarOpen(prefs.sidebarOpen);
    memoryManager.getConversations().then(savedChats => {
      if (savedChats.length > 0) setChats(savedChats.map(c => ({
        id: c.id,
        title: c.title,
        mode: c.mode,
        messages: c.messages || []
      })));
    });

  }, [user?.id]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, loading]);
  useEffect(() => { if (user) memoryManager.setPreference("preferredMode", activeMode); }, [activeMode]);
  useEffect(() => { if (user) memoryManager.setPreference("sidebarOpen", sidebarOpen); }, [sidebarOpen]);
  useEffect(() => { if (user) memoryManager.setPreference("voiceLanguage", voiceLanguage); }, [voiceLanguage]);

  // ── Chat Actions ────────────────────────────────────────────
  const newChat = () => {
    selectionRef.current = null;
    setActiveChatId(null);
    setMessages([]);
    setErr(null);
    setAttachedFile(null);
    setSelectedModel(null); // Reset to auto-routing for new conversations
    voiceEngine.stopSpeaking();
    setSpeakingId(null);
    agent.clearMessages(); // Clear agentic state on new chat
    setTimeout(() => inputRef.current?.focus(), 60);
  };

  const selectChat = async (id) => {
    selectionRef.current = id;
    const cached = chats.find(chat => chat.id === id);
    setActiveChatId(id);
    setErr(null);
    setMessages(cached?.messages || []);
    if (cached?.mode && MODES.some(mode => mode.id === cached.mode)) setActiveMode(cached.mode);
    const record = await memoryManager.getConversation(id);
    if (selectionRef.current === id && record) setMessages(record.messages || []);
    if (memoryManager.lastError) setErr(`Showing cached history. ${memoryManager.lastError}`);
  };

  const deleteChat = async (id) => {
    try {
      await memoryManager.deleteConversation(id);
      setChats(previous => previous.filter(chat => chat.id !== id));
      if (activeChatId === id) {
        selectionRef.current = null;
        setActiveChatId(null);
        setMessages([]);
      }
    } catch (error) { setErr(error.message); }
  };

  const speakText = (text, id) => {
    if (speakingId === id) {
      voiceEngine.stopSpeaking();
      setSpeakingId(null);
      return;
    }
    voiceEngine.stopSpeaking();
    setSpeakingId(id);
    const playback = voiceEngine.speak(text, voiceLanguage, {
      onEnd: () => setSpeakingId(null),
      onError: error => { setSpeakingId(null); setErr(`Could not read the response aloud: ${error?.message || error}`); }
    });
    if (playback === false) setSpeakingId(null);
    if (playback?.catch) playback.catch(error => { setSpeakingId(null); setErr(error.message); });
  };

  const copyText = (text, id) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(id);
      setTimeout(() => setCopied(null), 2000);
    });
  };

  // ── File Drag & Drop ────────────────────────────────────────
  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      if (!isFileSupported(file)) {
        setErr("File type not supported.");
        return;
      }
      readFileAsText(file).then(text =>
        setAttachedFile({ name: file.name, content: text, size: file.size })
      ).catch(e => setErr("Failed to read file: " + e.message));
    }
  }, []);
  const handleDragOver = useCallback((e) => { e.preventDefault(); setDragOver(true); }, []);
  const handleDragLeave = useCallback(() => setDragOver(false), []);

  const send = async (text) => {
    let prompt = (text || input).trim();
    if ((!prompt && !attachedFile && !attachedFiles.length) || busy) return false;
    const files = [...(attachedFile ? [attachedFile] : []), ...attachedFiles];
    if (files.length) prompt += `${prompt ? "\n\n" : ""}${files.map(file => `Attached file: ${file.name}\n${file.content}`).join("\n\n---\n\n")}`;
    setErr(null);
    setLoading(true);
    voiceEngine.stopSpeaking();
    setSpeakingId(null);
    const conversationId = activeChatId || `conv_${crypto.randomUUID()}`;
    const model = ModelRouter.getConfig(activeMode, selectedModel);
    try {
      if (!activeChatId) await backendClient.saveConversation({
        id: conversationId,
        title: (text || input || files[0]?.name || "Conversation").slice(0, 60),
        mode: activeMode
      });
      const task = await agent.sendMessage(prompt, {
        conversation_id: conversationId,
        provider: model.provider,
        model: model.model,
        instructions: [MODE_DIRECTIVES[activeMode], `Tone: ${tone}. ${responseLength.instruction || ""}`].filter(Boolean).join("\n"),
        metadata: { mode: activeMode, voice_language: voiceLanguage, tone, response_length: responseLength.id }
      });
      const actualId = task.conversation_id || conversationId;
      selectionRef.current = actualId;
      setActiveChatId(actualId);
      setChats(previous => previous.some(chat => chat.id === actualId) ? previous : [{
        id: actualId,
        title: (text || input || files[0]?.name || "Conversation").slice(0, 60),
        mode: activeMode,
        messages: []
      }, ...previous]);
      setInput("");
      setAttachedFile(null);
      setAttachedFiles([]);
      memoryManager.recordInteraction("prompt", { text: prompt.slice(0, 100), mode: activeMode });
      return true;
    } catch (error) {
      setErr(error.message || "The backend could not accept your message.");
      return false;
    } finally {
      setLoading(false);
    }
  };

  const modeColor = MODES.find(m => m.id === activeMode)?.color || "#FF2A2A";

  const activeCount = agent.tasks.filter(task => ['queued', 'running', 'awaiting_approval'].includes(task.status)).length;
  const toggleTasks = () => setActivePanel(previous => previous === 'tasks' ? null : 'tasks');
  return <ErrorBoundary><div className="lyra-workspace">
    {desktopModeActive ? <DesktopMode initialView={desktopInitialView} onExit={() => setDesktopModeActive(false)} conversationId={activeChatId} initialMessages={messages} selectedModel={selectedModel} onConversationChange={id => { selectionRef.current = id; setActiveChatId(id); }} /> : <>
      <Sidebar user={user} activeMode={activeMode} setActiveMode={setActiveMode} chats={chats} activeChatId={activeChatId} onNewChat={newChat} onSelectChat={selectChat} onDeleteChat={deleteChat} sidebarOpen={sidebarOpen} onDesktop={openTerminal} onTasks={toggleTasks} />
      <div className="workspace-main">
        <TopBar setSidebarOpen={setSidebarOpen} activeMode={activeMode} activePanel={activePanel} setActivePanel={setActivePanel} selectedModel={selectedModel} setSelectedModel={setSelectedModel} onDesktopMode={openTerminal} modeColor={modeColor} onTasks={toggleTasks} />
        <div className="workspace-service-strip"><div><span className={`connection-indicator ${agent.connected ? 'is-connected' : ''}`} /><span>{agent.connected ? 'Local service connected' : agent.recovering ? 'Connecting to local service…' : 'Local service disconnected'}</span><button onClick={agent.refresh} disabled={agent.recovering}>{agent.connected ? 'Refresh' : 'Reconnect'}</button></div><span className="workspace-active-tasks">{activeCount ? `${activeCount} active ${activeCount === 1 ? 'task' : 'tasks'}` : 'Your next move starts here'}<span className="service-shortcut">⌘ K</span></span></div>
        <div className="workspace-content"><main className="conversation-workspace" onDrop={handleDrop} onDragOver={handleDragOver} onDragLeave={handleDragLeave}>
          {dragOver && <div className="file-drop-overlay">Drop your document here</div>}
          <ChatArea user={user} messages={agent.agentMessages} loading={busy} err={err || agent.error} speakingId={speakingId} copied={copied} lyraInfo={lyraInfo} setLyraInfo={setLyraInfo} bottomRef={bottomRef} onCopy={copyText} onSpeak={speakText} agent={agent} onSuggest={text => { setInput(text); inputRef.current?.focus(); }} />
          <InputBar input={input} setInput={setInput} inputRef={inputRef} onSend={send} activeMode={activeMode} setActiveMode={setActiveMode} loading={busy} attachedFile={attachedFile} setAttachedFile={setAttachedFile} attachedFiles={attachedFiles} setAttachedFiles={setAttachedFiles} setErr={setErr} voiceLanguage={voiceLanguage} onVoiceLanguageChange={setVoiceLanguage} tone={tone} setTone={setTone} responseLength={responseLength} setResponseLength={setResponseLength} />
        </main>{activePanel === 'tasks' && <TaskPanel agent={agent} onSelectConversation={selectChat} />}</div>
      </div>
      <HudPanel isOpen={activePanel === 'settings'} title="Workspace settings" onClose={() => setActivePanel(null)}><div className="workspace-settings"><p>Provider credentials stay in the local backend. Model availability means a key is configured; each request still reports its actual outcome.</p><label>Voice language<select value={voiceLanguage} onChange={event => setVoiceLanguage(event.target.value)}><option value="en-US">English</option><option value="hi-IN">Hindi</option><option value="te-IN">Telugu</option></select></label><p>Saved context and task receipts are stored in SQLite. The browser retains a recovery cache of conversations.</p></div></HudPanel>
    </>}
    <KeyboardShortcuts onNewChat={newChat} onToggleMic={() => document.querySelector('.rtv-mic-btn, .va-mic-btn')?.click()} onFocusInput={() => inputRef.current?.focus()} onTogglePromptImprover={() => window.dispatchEvent(new Event('lyra:improve-prompt'))} onSwitchMode={setActiveMode} modes={MODES} />
  </div></ErrorBoundary>;
}
