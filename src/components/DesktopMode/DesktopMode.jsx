import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Brain, MessageSquare, Mic, Send, Square, Terminal, Volume2 } from 'lucide-react';
import { useLyraAgent } from '../../hooks/useLyraAgent';
import { ModelRouter } from '../../modules/ModelRouter';
import { voiceManager } from '../../modules/VoiceManager';
import MemoryVault from '../MemoryVault/MemoryVault';
import MarkdownContent from '../MarkdownContent/MarkdownContent';
import ToolConfirmationCard from '../ToolConfirmationCard/ToolConfirmationCard';
import TaskPanel from '../Tasks/TaskPanel';
import AITerminal from './AITerminal';
import './DesktopMode.css';
const EMPTY_MESSAGES = [];
export default function DesktopMode({ onExit, conversationId = null, initialMessages = EMPTY_MESSAGES, selectedModel = null, onConversationChange, initialView = 'chat' }) {
  const [sessionId, setSessionId] = useState(conversationId);
  const [draft, setDraft] = useState(''); const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(''); const [view, setView] = useState(initialView === 'terminal' ? 'terminal' : 'chat');
  const [memoryOpen, setMemoryOpen] = useState(false); const [voiceState, setVoiceState] = useState('idle');
  const [startingMic, setStartingMic] = useState(false); const [interim, setInterim] = useState('');
  const [readReplies, setReadReplies] = useState(false);
  const agent = useLyraAgent({ conversationId: sessionId, initialMessages });
  const mounted = useRef(false); const micRequested = useRef(false); const sendRef = useRef(null);
  const inputRef = useRef(null); const endRef = useRef(null); const sessionRef = useRef(sessionId);
  const speakThisTurn = useRef(false); const spokenTasks = useRef(new Set());
  const busy = submitting || agent.isThinking;
  const microphoneActive = startingMic || ['requesting', 'active', 'transcribing'].includes(voiceState) || !!interim;
  const stopAudio = useCallback(() => { voiceManager.stopSpeaking(); setVoiceState(previous => previous === 'speaking' ? 'idle' : previous); }, []);
  useEffect(() => { if (conversationId) { sessionRef.current = conversationId; setSessionId(conversationId); } }, [conversationId]);
  const sendCommand = async (text, isVoice = false) => {
    const prompt = text.trim(); if (!prompt || busy) return false;
    if (!agent.connected) { setError('The backend is disconnected. Your draft is preserved.'); return false; }
    setSubmitting(true); setError(''); stopAudio();
    const id = sessionRef.current || `conv_${globalThis.crypto.randomUUID()}`;
    const config = ModelRouter.getConfig('agent', selectedModel);
    try {
      const task = await agent.sendMessage(prompt, { mode: 'agent', conversation_id: id, model: config.model, provider: config.provider, metadata: { mode: 'agent', is_voice: isVoice } });
      sessionRef.current = task.conversation_id || id; setSessionId(sessionRef.current); onConversationChange?.(sessionRef.current);
      speakThisTurn.current = isVoice || readReplies; setDraft(''); return true;
    } catch (failure) { setError(failure.message); if (isVoice) setDraft(prompt); return false; }
    finally { if (mounted.current) setSubmitting(false); }
  };
  sendRef.current = sendCommand;
  const interrupt = useCallback(() => {
    micRequested.current = false; voiceManager.setContinuousMode(false); voiceManager.stop(false);
    setStartingMic(false); setVoiceState('idle'); setInterim(''); speakThisTurn.current = false;
    stopAudio(); return agent.stopResponse();
  }, [agent.stopResponse, stopAudio]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; micRequested.current = false; voiceManager.setContinuousMode(false); voiceManager.stop(false); stopAudio(); };
  }, [stopAudio]);
  useEffect(() => {
    if (view !== 'chat') return;
    voiceManager.listener.onCommand(command => {
      voiceManager.stop(false); micRequested.current = false; setVoiceState('idle'); setInterim(''); sendRef.current(command, true);
    });
    voiceManager.onStateChange(setVoiceState);
    voiceManager.onTranscript(({ interim: text }) => setInterim(text || ''));
    voiceManager.onError(reason => {
      micRequested.current = false; setStartingMic(false); setVoiceState('idle'); setInterim('');
      setError(reason === 'mic-denied' ? 'Microphone access was denied. You can type your message below.' : String(reason?.message || reason || 'The microphone could not complete transcription.'));
    });
    voiceManager.setContinuousMode(false);
    return () => { voiceManager.onStateChange(null); voiceManager.onTranscript(null); voiceManager.onError(null); voiceManager.listener.onCommand(null); voiceManager.stop(false); };
  }, [view]);
  useEffect(() => {
    if (!speakThisTurn.current) return;
    const answer = [...agent.agentMessages].reverse().find(message => message.role === 'assistant' && message.status === 'completed' && message.task_id);
    if (answer && !spokenTasks.current.has(answer.task_id)) { spokenTasks.current.add(answer.task_id); Promise.resolve(voiceManager.speak(answer.content)).catch(failure => setError(failure.message)); }
  }, [agent.agentMessages]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [agent.agentMessages, interim]);
  const toggleMic = async () => {
    if (voiceState === 'transcribing') { micRequested.current = false; voiceManager.stop(false); setVoiceState('idle'); setInterim(''); return; }
    if (voiceState === 'active') { voiceManager.stop(true); setInterim('Transcribing…'); return; }
    if (startingMic) { micRequested.current = false; voiceManager.stop(false); setStartingMic(false); return; }
    stopAudio(); setError(''); micRequested.current = true; setStartingMic(true);
    const started = await voiceManager.startListening();
    if (!mounted.current || !micRequested.current) { voiceManager.stop(false); return; }
    setStartingMic(false); if (!started) micRequested.current = false;
  };
  const canStop = busy || microphoneActive || voiceState === 'speaking';
  useEffect(() => {
    const handleKey = event => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k' && view === 'chat') { event.preventDefault(); inputRef.current?.focus(); }
      else if (event.key === 'Escape' && canStop && !memoryOpen) { event.preventDefault(); interrupt(); }
    };
    window.addEventListener('keydown', handleKey); return () => window.removeEventListener('keydown', handleKey);
  }, [canStop, interrupt, memoryOpen, view]);
  const submit = event => { event.preventDefault(); sendCommand(draft); };
  return <div className="desktop-assistant">
    <header className="desktop-assistant-header"><div className="desktop-assistant-title"><span className="desktop-assistant-mark" aria-hidden="true">L</span><div><strong>Lyra desktop</strong><span>Your assistant for this computer</span></div></div><div className="desktop-assistant-header-actions"><span className={`desktop-connection ${agent.connected ? 'is-connected' : ''}`} role="status"><i />{agent.recovering ? 'Connecting…' : agent.connected ? 'Connected' : 'Disconnected'}</span><button onClick={onExit}><ArrowLeft size={16} />Back to chat</button></div></header>
    <div className="desktop-assistant-body"><aside className="desktop-assistant-sidebar"><nav aria-label="Desktop tools"><button className={view === 'chat' ? 'is-selected' : ''} onClick={() => setView('chat')}><MessageSquare size={18} />Assistant</button><button className={view === 'terminal' ? 'is-selected' : ''} disabled={busy || microphoneActive} onClick={() => { stopAudio(); setView('terminal'); }}><Terminal size={18} />Terminal</button><button onClick={() => setMemoryOpen(true)}><Brain size={18} />Memory</button></nav><p>Ask a question, work with local files, or request a desktop action. Changes appear for approval before execution.</p>{!agent.connected && <button className="desktop-reconnect" onClick={agent.refresh}>Reconnect</button>}</aside>
    <main className="desktop-assistant-main">{view === 'terminal' ? <div className="desktop-terminal"><AITerminal conversationId={sessionId} selectedModel={selectedModel} /></div> : <>
      <div className="desktop-conversation" role="log" aria-label="Desktop conversation" aria-live="polite">
        {!agent.agentMessages.length && <div className="desktop-empty"><span>DESKTOP ASSISTANT</span><h1>What would you like to do?</h1><p>Talk to Lyra or type below. Your conversation, approvals, and tool receipts appear here.</p></div>}
        {agent.agentMessages.map((message, index) => <article key={message.id || index} className={`desktop-message desktop-message-${message.role}`}><div className="desktop-message-meta"><strong>{message.role === 'user' ? 'You' : message.tool || 'Lyra'}</strong>{message.provider && <span>{message.provider} · {message.model}</span>}{message.status && <span>{message.status.replaceAll('_', ' ')}</span>}</div>
          {message.role === 'tool_call' ? <ToolConfirmationCard confirmation={message.confirmation} onConfirm={agent.confirmTool} onDeny={id => agent.confirmTool(id, false)} resolved={message.resolved} approved={message.approved} /> : message.role === 'tool' ? <pre className="desktop-tool-receipt">{typeof message.content === 'string' ? message.content : JSON.stringify(message.content, null, 2)}</pre> : message.role === 'assistant' ? <MarkdownContent content={message.content} color="#a7d6c0" /> : <p className="desktop-user-text">{message.content}</p>}
        </article>)}<div ref={endRef} />
      </div><div className="desktop-composer-wrap">{(error || agent.error) && <div className="desktop-error" role="alert">{error || agent.error}</div>}<div className="desktop-activity" role="status">{voiceState === 'transcribing' ? 'Transcribing…' : interim || (voiceState === 'speaking' ? 'Speaking…' : busy ? 'Task in progress…' : '')}</div>
      <form className="desktop-composer" onSubmit={submit}><textarea ref={inputRef} aria-label="Message Lyra desktop" placeholder="Message Lyra…" value={draft} onChange={event => setDraft(event.target.value)} rows={2} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!microphoneActive) submit(event); } }} /><div className="desktop-composer-actions"><label className="desktop-read-replies"><input type="checkbox" checked={readReplies} onChange={event => { setReadReplies(event.target.checked); if (!event.target.checked) { speakThisTurn.current = false; stopAudio(); } }} /><Volume2 size={15} />Read replies aloud</label><div><button type="button" className={microphoneActive ? 'desktop-mic is-active' : 'desktop-mic'} aria-label={voiceState === 'transcribing' ? 'Cancel transcription' : startingMic ? 'Cancel microphone' : microphoneActive ? 'Send recording' : 'Start microphone'} onClick={toggleMic} disabled={!agent.connected || busy}><Mic size={18} /></button>{canStop && <button type="button" className="desktop-stop" aria-label="Stop response" onClick={interrupt}><Square size={16} /></button>}<button type="submit" className="desktop-send" aria-label="Send message" disabled={!draft.trim() || busy || microphoneActive || !agent.connected}><Send size={17} /></button></div></div></form><p className="desktop-composer-hint">Enter to send · Shift + Enter for a new line</p></div>
    </>}</main><TaskPanel agent={agent} onSelectConversation={id => { sessionRef.current = id; setSessionId(id); onConversationChange?.(id); }} /></div><MemoryVault isOpen={memoryOpen} onClose={() => setMemoryOpen(false)} />
  </div>;
}
