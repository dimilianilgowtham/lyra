/** Terminal work is a conversation; commands retain their real approvals and receipts. */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUp, ChevronRight, Crosshair, FolderOpen, MessageSquare, RefreshCw, Square, Terminal, Trash2 } from 'lucide-react';
import { backendClient } from '../../modules/BackendClient';
import { useLyraAgent } from '../../hooks/useLyraAgent';
import { ModelRouter } from '../../modules/ModelRouter';
import { terminalConversationId, terminalIsActive, terminalResponse, terminalStepLabel, terminalToolSteps } from '../../modules/TerminalSession';
import MarkdownContent from '../MarkdownContent/MarkdownContent';
import ToolConfirmationCard from '../ToolConfirmationCard/ToolConfirmationCard';
import VoiceAssistant from '../VoiceAssistant/VoiceAssistant';
import './AITerminal.css';

const EMPTY_MESSAGES = [];
const EXAMPLES = [
  { label: 'Map this project', prompt: 'Inspect this working directory. Explain the project structure, how to run it, and the local security-relevant configuration. Do not change files.' },
  { label: 'Find installed tools', prompt: 'Check which security analysis tools are already installed on this computer and report their versions. Do not install anything or scan any network targets.' },
  { label: 'Analyze a local log', prompt: 'Help me analyze a local log file for suspicious activity. First list likely log files in this working directory and ask which one to examine.' },
];

function StepOutput({ step }) {
  const result = step.result;
  const shell = step.tool === 'execute_command';
  const duration = result?.duration_ms ?? step.receipt?.duration_ms;
  const hasResult = result !== undefined && result !== null && (typeof result !== 'object' || Object.keys(result).length > 0);
  const exit = shell && result?.exit_code !== undefined && result?.exit_code !== null ? result.exit_code : null;
  return <section className={`terminal-execution terminal-execution-${step.status}`} aria-label={shell ? 'Command execution' : 'Tool execution'}>
    <div className="terminal-execution-heading"><span className="terminal-command-prefix" aria-hidden="true">{shell ? '$' : '↳'}</span><code>{terminalStepLabel(step)}</code><span className={`terminal-status terminal-status-${step.status}`}>{step.status?.replaceAll('_', ' ')}</span></div>
    {(step.arguments.cwd || result?.cwd || exit !== null || duration > 0) && <div className="terminal-execution-meta">{(result?.cwd || step.arguments.cwd) && <span>{result?.cwd || step.arguments.cwd}</span>}{exit !== null && <span className={exit === 0 ? '' : 'terminal-exit-failed'}>exit {exit}</span>}{duration > 0 && <span>{(duration / 1000).toFixed(2)}s {result?.duration_ms !== undefined ? 'runtime' : 'elapsed'}</span>}</div>}
    {shell && hasResult ? <div className="terminal-streams">
      {result.stdout !== undefined && <div className="terminal-stream"><span>stdout{result.stdout_truncated ? ' · truncated' : ''}</span><pre>{result.stdout || '(empty)'}</pre></div>}
      {!!result.stderr && <div className="terminal-stream terminal-stderr"><span>stderr{result.stderr_truncated ? ' · truncated' : ''}</span><pre>{result.stderr}</pre></div>}
      {result.error && <div className="terminal-step-error">{result.error}</div>}
      {result.verification === 'process_exit_only' && <p className="terminal-verification">Process result only. Changes require a separate check.</p>}
    </div> : hasResult ? <details className="terminal-tool-details"><summary>View tool result</summary><pre>{typeof result === 'string' ? result : JSON.stringify(result, null, 2)}</pre></details> : <p className="terminal-step-pending">{step.status === 'awaiting_approval' ? 'Waiting for your decision below.' : step.status === 'running' ? 'Command is running. Output appears when this step finishes.' : 'Step queued.'}</p>}
  </section>;
}

export default function AITerminal({ conversationId = null, selectedModel = null, externalVoiceCommand }) {
  const [sessionId, setSessionId] = useState(() => terminalConversationId(conversationId));
  const [cwd, setCwd] = useState(''); const [scope, setScope] = useState('');
  const [input, setInput] = useState(''); const [mode, setMode] = useState('chat');
  const [error, setError] = useState(''); const [submitting, setSubmitting] = useState(false);
  const [hidden, setHidden] = useState([]); const [voiceLanguage, setVoiceLanguage] = useState('en-US');
  const agent = useLyraAgent({ conversationId: sessionId, initialMessages: EMPTY_MESSAGES });
  const mounted = useRef(false); const inputRef = useRef(null); const endRef = useRef(null); const contextEdited = useRef(false);
  const taskList = useMemo(() => agent.tasks.filter(task => task.conversation_id === sessionId).sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || ''))), [agent.tasks, sessionId]);
  const activeTasks = taskList.filter(terminalIsActive); const busy = submitting || activeTasks.length > 0;
  const visibleTasks = taskList.filter(task => !hidden.includes(task.id));
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (conversationId) { setSessionId(terminalConversationId(conversationId)); setHidden([]); } }, [conversationId]);
  useEffect(() => { let cancelled = false; contextEdited.current = false; setCwd(''); setScope(''); backendClient.request('/api/terminal/context').then(context => { if (!cancelled && context.cwd) setCwd(previous => previous || context.cwd); }).catch(failure => { if (!cancelled) setError(`Working directory unavailable: ${failure.message}`); }); return () => { cancelled = true; }; }, [sessionId]);
  useEffect(() => { if (contextEdited.current) return; const saved = [...taskList].reverse().find(task => task.metadata?.terminal); if (saved?.metadata.cwd) setCwd(saved.metadata.cwd); if (saved?.metadata.scope) setScope(saved.metadata.scope); }, [taskList, sessionId]);
  useEffect(() => { if (visibleTasks.length) endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); else endRef.current?.parentElement?.scrollTo?.({ top: 0 }); }, [agent.details, sessionId, visibleTasks.length]);
  useEffect(() => {
    if (!externalVoiceCommand) return;
    const text = typeof externalVoiceCommand === 'string' ? externalVoiceCommand : externalVoiceCommand.text;
    if (text?.trim()) { setInput(previous => previous ? `${previous} ${text.trim()}` : text.trim()); inputRef.current?.focus(); }
  }, [externalVoiceCommand]);

  const send = async () => {
    const prompt = input.trim(); if (!prompt || busy) return;
    if (!agent.connected) { setError('The local service is disconnected. Your instruction is preserved.'); return; }
    setError(''); setSubmitting(true);
    const config = ModelRouter.getConfig('agent', selectedModel);
    const metadata = { terminal: true, cwd: cwd.trim(), scope: scope.trim() };
    try {
      if (mode === 'shell') {
        await backendClient.runTool('execute_command', { command: prompt, ...(metadata.cwd ? { cwd: metadata.cwd } : {}) }, { conversation_id: sessionId, prompt, metadata });
        await agent.refresh();
      } else await agent.sendMessage(prompt, { conversation_id: sessionId, mode: 'terminal', metadata, provider: config.provider, model: config.model });
      if (mounted.current) setInput('');
    } catch (failure) { if (mounted.current) setError(failure.message || 'The task could not start.'); }
    finally { if (mounted.current) setSubmitting(false); }
  };
  const submit = event => { event.preventDefault(); return send(); };
  const prefill = value => { setInput(value); setMode('chat'); inputRef.current?.focus(); };

  return <div className="ai-terminal-container terminal-chat-workspace">
    <header className="terminal-workspace-header"><div className="terminal-title"><span className="terminal-title-icon"><Terminal size={20} /></span><div><span className="terminal-eyebrow">LYRA / LOCAL OPERATIONS</span><h1>Terminal workspace<span>.</span></h1></div></div><div className="terminal-header-actions"><span className={`terminal-connection ${agent.connected ? 'is-connected' : ''}`} role="status"><i />{agent.recovering ? 'Connecting' : agent.connected ? 'Service connected' : 'Disconnected'}</span><button type="button" className="terminal-icon-button" aria-label="Refresh terminal tasks" title="Refresh tasks" onClick={agent.refresh}><RefreshCw size={15} /></button><button type="button" className="terminal-icon-button" aria-label="Clear terminal view" title="Clear view; saved tasks remain in history" onClick={() => setHidden(taskList.filter(task => !terminalIsActive(task)).map(task => task.id))}><Trash2 size={15} /></button></div></header>
    <div className="terminal-context-row"><label><span><FolderOpen size={13} />Working directory</span><input aria-label="Working directory" value={cwd} onChange={event => { contextEdited.current = true; setCwd(event.target.value); }} placeholder="Configured workspace root" disabled={busy} spellCheck="false" /></label><label><span><Crosshair size={13} />Assessment context <small>optional</small></span><input aria-label="Assessment context" value={scope} onChange={event => { contextEdited.current = true; setScope(event.target.value); }} placeholder="Your approved lab, target, or evidence scope" disabled={busy} /></label></div>
    <div className="terminal-conversation" role="log" aria-label="Terminal conversation" aria-live="polite">
      {!visibleTasks.length && <div className="terminal-welcome"><div className="terminal-welcome-index">01 / REQUEST → REVIEW → EXECUTE</div><h2>Your instruction.<br /><em>A traceable result.</em></h2><p>Describe the work in plain language. Lyra can inspect files, propose commands, run approved steps, and explain the actual results.</p><div className="terminal-examples">{EXAMPLES.map((example, index) => <button type="button" key={example.label} onClick={() => prefill(example.prompt)} disabled={busy}><span>0{index + 1}</span>{example.label}<ChevronRight size={16} /></button>)}</div><div className="terminal-welcome-note"><span aria-hidden="true">↳</span> Start with your working directory and assessment context. Nothing runs from an example until you send it and approve the command.</div></div>}
      {visibleTasks.map(task => {
        const detail = agent.details[task.id]; const steps = terminalToolSteps(detail); const response = terminalResponse(detail, task);
        const approvals = detail?.approvals?.filter(approval => approval.approved === undefined || approval.approved === null) || [];
        return <article className="terminal-turn" key={task.id} aria-label="Terminal task">
          <div className="terminal-user-message"><span className="terminal-turn-avatar">YOU</span><div><span className="terminal-message-label">Instruction</span><p>{task.prompt || task.arguments?.command}</p></div></div>
          <div className="terminal-agent-work"><div className="terminal-turn-heading"><span className="terminal-agent-mark">✳</span><strong>Lyra</strong><span className={`terminal-status terminal-status-${task.status}`}>{task.status.replaceAll('_', ' ')}</span><div className="terminal-turn-actions">{terminalIsActive(task) && <button type="button" className="terminal-text-button" aria-label="Stop terminal task" onClick={() => agent.cancelTask(task.id)}><Square size={12} />Stop</button>}{task.status === 'interrupted' && <button type="button" className="terminal-text-button" aria-label="Resume terminal task" onClick={() => agent.resumeTask(task.id)}>Resume task</button>}</div></div>
            {steps.map(step => <StepOutput key={step.id} step={step} />)}
            {approvals.map(approval => <ToolConfirmationCard key={approval.request_id} confirmation={approval} onConfirm={agent.confirmTool} onDeny={id => agent.confirmTool(id, false)} />)}
            {response && <div className="terminal-assistant-answer"><MarkdownContent content={response} color="#d0df91" /></div>}
            {task.error && <p className="terminal-step-error" role="alert">{task.error}</p>}
            {terminalIsActive(task) && !steps.length && !response && <p className="terminal-working"><span />{task.status === 'queued' ? 'Task queued with the local service.' : 'Working through your instruction…'}</p>}
            {(task.result?.provider || task.provider) && <div className="terminal-model-receipt">{task.result?.provider || task.provider}{(task.result?.model || task.model) ? ` / ${task.result?.model || task.model}` : ''}</div>}
          </div>
        </article>;
      })}<div ref={endRef} />
    </div>
    <div className="terminal-composer-region">{(error || agent.error) && <div className="terminal-service-error" role="alert">{error || agent.error}</div>}<form className="terminal-composer" onSubmit={submit}><div className="terminal-composer-top"><div className="terminal-mode-switch" aria-label="Terminal input mode"><button type="button" aria-label="Terminal chat mode" aria-pressed={mode === 'chat'} className={mode === 'chat' ? 'is-active' : ''} onClick={() => setMode('chat')} disabled={busy}><MessageSquare size={13} />Instruction</button><button type="button" aria-label="Shell command mode" aria-pressed={mode === 'shell'} className={mode === 'shell' ? 'is-active' : ''} onClick={() => setMode('shell')} disabled={busy}><Terminal size={13} />Shell command</button></div><span className="terminal-mode-hint">{mode === 'shell' ? 'Exact command · approval required' : 'Plain language · multiple steps'}</span></div><textarea ref={inputRef} aria-label={mode === 'shell' ? 'Shell command' : 'Terminal instruction'} placeholder={mode === 'shell' ? 'Enter the exact command to review and run…' : 'Tell Lyra what to inspect, analyze, or do in this workspace…'} value={input} rows={2} onChange={event => setInput(event.target.value)} spellCheck={mode !== 'shell'} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); } }} /><div className="terminal-composer-bottom"><span><span className="terminal-prompt-symbol">{mode === 'shell' ? '$' : '↳'}</span>{mode === 'shell' ? 'One command at a time' : 'Review proposed commands before execution'}</span><div><VoiceAssistant onTranscript={text => { if (text?.trim()) { setInput(previous => previous ? `${previous} ${text.trim()}` : text.trim()); inputRef.current?.focus(); } }} language={voiceLanguage} onLanguageChange={setVoiceLanguage} disabled={busy} /><button type="submit" className="terminal-send" aria-label="Send terminal instruction" title={mode === 'shell' ? 'Request command execution' : 'Send terminal instruction'} disabled={!input.trim() || busy || !agent.connected}><ArrowUp size={19} /></button></div></div></form><div className="terminal-composer-footer"><span>Dictation fills your draft. You choose when to send.</span><span><kbd>↵</kbd> send <i /> <kbd>⇧ ↵</kbd> new line</span></div></div>
  </div>;
}
