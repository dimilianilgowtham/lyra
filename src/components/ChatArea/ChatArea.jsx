import React from 'react';
import { ArrowUpRight, FolderOpen, Feather, Compass, Copy, Check, Volume2, Square, CheckCircle2, AlertCircle, Terminal } from 'lucide-react';
import MarkdownContent from '../MarkdownContent/MarkdownContent';
import ToolConfirmationCard from '../ToolConfirmationCard/ToolConfirmationCard';
import LyraInfoModal from '../common/LyraInfoModal';

const STARTERS = [
  { icon: FolderOpen, title: 'Explore a project', description: 'Find the structure. See the next step.', prompt: 'Inspect this workspace and explain its structure, main workflows, and what needs attention. Base your findings on actual files.' },
  { icon: Feather, title: 'Make something useful', description: 'Turn a rough idea into a clear draft.', prompt: 'Help me turn an idea into a useful document. Ask what the document should achieve before drafting.' },
  { icon: Compass, title: 'Work through a task', description: 'A considered plan. Real follow-through.', prompt: 'Help me plan a task and carry it through step by step. Ask me for the goal, then use tools to verify the results.' },
];

export default function ChatArea({ user, messages = [], loading, err, speakingId, copied, lyraInfo, setLyraInfo, bottomRef, onCopy, onSpeak, agent, onSuggest }) {
  const date = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date());
  return <div className="conversation-scroll" aria-label="Conversation">
    {lyraInfo && <LyraInfoModal onClose={() => setLyraInfo(false)} />}
    {!messages.length && <section className="workspace-welcome"><div className="welcome-date"><span />{date}</div><div className="welcome-emblem" aria-hidden="true"><span>✳</span><i /><i /></div><h1>A little clarity.<br /><em>A lot of possibility.</em></h1><p>Good to see you, {user?.name?.split(' ')[0] || 'there'}.<br />What would you like to move forward?</p><div className="starter-grid">{STARTERS.map(item => <button className="starter-card" key={item.title} onClick={() => onSuggest?.(item.prompt)}><item.icon size={19} strokeWidth={1.4} /><ArrowUpRight className="starter-arrow" size={14} /><strong>{item.title}</strong><span>{item.description}</span></button>)}</div><div className="welcome-footnote"><span>FILES & DOCUMENTS</span><i /> <span>MULTI-STEP TASKS</span><i /><span>VOICE & MEMORY</span></div></section>}
    <div className="conversation-messages">{messages.map((message, index) => {
      if (message.role === 'tool_call') return <ToolConfirmationCard key={message.id || index} confirmation={message.confirmation} onConfirm={agent?.confirmTool} onDeny={id => agent?.confirmTool(id, false)} resolved={message.resolved} approved={message.approved} />;
      if (message.role === 'tool') return <details key={message.id || index} className={`tool-receipt ${['failed','denied','cancelled'].includes(message.status) ? 'has-error' : ''}`}><summary><Terminal size={14} /><strong>{(message.tool || 'Tool').replaceAll('_', ' ')}</strong><span>{message.verified ? 'Verified' : message.status || 'Result'}</span></summary><pre>{typeof message.content === 'string' ? message.content : JSON.stringify(message.content, null, 2)}</pre></details>;
      if (message.role === 'error') return <div key={message.id || index} className="conversation-error" role="alert"><AlertCircle size={16} /><span>{String(message.content || 'The task could not complete.')}</span></div>;
      const isUser = message.role === 'user';
      return <article key={message.id || index} className={`message ${isUser ? 'message-user' : 'message-assistant'}`}><div className="message-avatar">{isUser ? user?.name?.[0] || 'Y' : '✳'}</div><div className="message-main"><div className="message-heading"><strong>{isUser ? 'You' : 'Lyra'}</strong>{message.model && <span>{message.model}</span>}{message.status === 'interrupted' && <span>Interrupted</span>}</div>{isUser ? <p className="user-message-text">{String(message.content || '')}</p> : <MarkdownContent content={String(message.content || '')} color="#d1e9a5" />}{!isUser && <div className="message-actions"><button aria-label="Copy response" onClick={() => onCopy?.(String(message.content || ''), message.id || index)}>{copied === (message.id || index) ? <Check size={13} /> : <Copy size={13} />}</button><button aria-label={speakingId === (message.id || index) ? 'Stop reading' : 'Read response aloud'} onClick={() => onSpeak?.(String(message.content || ''), message.id || index)}>{speakingId === (message.id || index) ? <Square size={12} /> : <Volume2 size={13} />}</button></div>}</div></article>;
    })}{loading && <div className="working-indicator" role="status"><span /><span /><span /><p>Working on your request</p><button onClick={agent?.stopResponse}>Stop</button></div>}{err && <div className="conversation-error" role="alert"><AlertCircle size={16} /><span>{err}</span></div>}<div ref={bottomRef} /></div>
  </div>;
}
