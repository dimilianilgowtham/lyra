import React, { useCallback, useEffect, useState } from 'react';
import { backendClient } from '../../modules/BackendClient';
import { ACTIVE_TASK_STATUSES } from '../../modules/TaskController';
import ToolConfirmationCard from '../ToolConfirmationCard/ToolConfirmationCard';
import './Tasks.css';
export default function TaskPanel({ agent, onSelectConversation }) {
  const [open, setOpen] = useState(true);
  const [reminders, setReminders] = useState([]);
  const [text, setText] = useState(''); const [due, setDue] = useState('');
  const [error, setError] = useState(''); const [saving, setSaving] = useState(false);
  const refreshReminders = useCallback(async () => {
    try { const data = await backendClient.listReminders(); setReminders(data.reminders || []); setError(''); }
    catch (failure) { setError(failure.message); }
  }, []);
  useEffect(() => {
    if (!agent.connected) return;
    refreshReminders();
    const timer = setInterval(refreshReminders, 30000);
    return () => clearInterval(timer);
  }, [agent.connected, refreshReminders]);
  const addReminder = async event => {
    event.preventDefault(); if (!text.trim() || !due || saving) return;
    setSaving(true); setError('');
    try { await backendClient.createReminder(text.trim(), new Date(due).toISOString()); setText(''); setDue(''); await refreshReminders(); }
    catch (failure) { setError(failure.message); }
    finally { setSaving(false); }
  };
  const removeReminder = async id => {
    try { const data = await backendClient.deleteReminder(id); if (data.success === false) throw new Error(data.error || 'Reminder was not deleted'); await refreshReminders(); }
    catch (failure) { setError(failure.message); }
  };
  return <aside className={`task-panel ${open ? 'is-open' : ''}`} aria-label="Tasks and reminders">
    <button className="task-panel-toggle" onClick={() => setOpen(value => !value)}>Tasks & reminders <span>{open ? '−' : '+'}</span></button>
    {open && <div className="task-panel-body">
      <div className="task-panel-title"><strong>Tasks</strong><button onClick={agent.refresh} disabled={agent.recovering}>Refresh</button></div>
      {!agent.tasks.length && <p className="task-empty">{agent.connected ? 'No tasks yet.' : 'Connect to the backend to load tasks.'}</p>}
      {agent.tasks.slice(0, 20).map(task => <section className="task-item" key={task.id}>
        <button className="task-prompt" onClick={() => task.conversation_id && onSelectConversation?.(task.conversation_id)}>{task.prompt || task.tool || 'Task'}</button>
        <div className="task-meta"><span>{task.status?.replaceAll('_', ' ')}</span><span>{task.result?.provider || task.provider}{(task.result?.model || task.model) && ` · ${task.result?.model || task.model}`}</span></div>
        {task.error && <p className="task-error">{task.error}</p>}
        <div className="task-actions">{ACTIVE_TASK_STATUSES.has(task.status) && <button onClick={() => agent.cancelTask(task.id)}>Stop task</button>}{task.status === 'interrupted' && <button onClick={() => agent.resumeTask(task.id)}>Resume task</button>}</div>
        {(agent.details[task.id]?.approvals || []).filter(approval => approval.approved === null || approval.approved === undefined).map(approval => <ToolConfirmationCard key={approval.request_id} confirmation={approval} onConfirm={agent.confirmTool} onDeny={id => agent.confirmTool(id, false)} />)}
        {(agent.details[task.id]?.events || []).some(event => event.type === 'tool_status' && event.payload?.result !== undefined) && <details className="task-receipts"><summary>Tool receipts</summary>{agent.details[task.id].events.filter(event => event.type === 'tool_status' && event.payload?.result !== undefined).map(event => <div key={event.seq}><strong>{event.payload.tool} · {event.payload.status}</strong><pre>{typeof event.payload.result === 'string' ? event.payload.result : JSON.stringify(event.payload.result, null, 2)}</pre></div>)}</details>}
      </section>)}
      <div className="task-panel-title"><strong>Reminders</strong><button onClick={refreshReminders} disabled={!agent.connected}>Refresh</button></div>
      {reminders.map(reminder => <div className="reminder-item" key={reminder.id}><strong>{reminder.text}</strong><span>{new Date(reminder.due_at).toLocaleString()} · {reminder.status || (reminder.fired_at ? 'Delivered' : 'Scheduled')}</span><button onClick={() => removeReminder(reminder.id)}>Delete</button></div>)}
      {agent.connected && !reminders.length && <p className="task-empty">No reminders.</p>}
      <form className="reminder-form" onSubmit={addReminder}><label>Reminder<input value={text} onChange={event => setText(event.target.value)} placeholder="What to remember" required /></label><label>Due in your local time<input type="datetime-local" value={due} onChange={event => setDue(event.target.value)} required /></label><button disabled={!agent.connected || saving || !text.trim() || !due}>{saving ? 'Saving…' : 'Add reminder'}</button></form>
      {(error || agent.error) && <p className="task-error" role="alert">{error || agent.error}</p>}
    </div>}
  </aside>;
}
