import { useCallback, useEffect, useMemo, useState } from 'react';
import { taskController, taskMessages, ACTIVE_TASK_STATUSES } from '../modules/TaskController';
export function useLyraAgent({ conversationId = null, initialMessages = [] } = {}) {
  const [snapshot, setSnapshot] = useState(() => taskController.snapshot());
  const [localError, setLocalError] = useState('');
  useEffect(() => {
    const unsubscribe = taskController.subscribe(setSnapshot);
    taskController.recover().catch(() => {});
    const removeStatus = globalThis.window?.lyra?.onBackendStatus?.(status => { if (status.state === "ready") taskController.recover().catch(() => {}); });
    return () => { unsubscribe(); removeStatus?.(); };
  }, []);
  const relevantTasks = snapshot.tasks.filter(task => task.conversation_id === conversationId);
  const agentMessages = useMemo(() => {
    const messages = [...initialMessages]; const available = new Map();
    const positions = new Map(messages.map((message, index) => [message.id, index]).filter(([id]) => id));
    for (const message of initialMessages) { const key = `${message.role}:${message.content}`; available.set(key, (available.get(key) || 0) + 1); }
    const details = Object.values(snapshot.details).filter(detail => detail.task.conversation_id === conversationId).sort((a, b) => String(a.task.created_at || '').localeCompare(String(b.task.created_at || '')));
    for (const detail of details) for (const message of taskMessages(detail)) {
      if (message.id && positions.has(message.id)) { messages[positions.get(message.id)] = message; continue; }
      const key = `${message.role}:${message.content}`;
      if ((available.get(key) || 0) > 0 && !['tool', 'tool_call', 'error'].includes(message.role)) available.set(key, available.get(key) - 1);
      else messages.push(message);
    }
    return messages;
  }, [conversationId, initialMessages, snapshot.details]);
  const sendMessage = useCallback(async (prompt, options = {}) => {
    setLocalError('');
    try { return await taskController.start({ prompt, conversation_id: options.conversation_id || conversationId, mode: 'agent', ...options }); }
    catch (error) { setLocalError(error.message); throw error; }
  }, [conversationId]);
  const act = useCallback(async callback => { setLocalError(''); try { await callback(); } catch (error) { setLocalError(error.message); } }, []);
  const confirmTool = useCallback((requestId, approved = true) => {
    const detail = Object.values(taskController.snapshot().details).find(item => item.approvals?.some(approval => approval.request_id === requestId) || item.events?.some(event => event.payload?.request_id === requestId));
    if (detail) return act(() => taskController.approve(detail.task.id, requestId, approved));
  }, [act]);
  return {
    agentMessages, tasks: snapshot.tasks, details: snapshot.details, health: snapshot.health,
    connected: snapshot.connected, recovering: snapshot.recovering, error: localError || snapshot.error,
    isThinking: relevantTasks.some(task => ACTIVE_TASK_STATUSES.has(task.status)), sendMessage, confirmTool,
    clearMessages() { setLocalError(''); }, cancelTask: id => act(() => taskController.cancel(id)), resumeTask: id => act(() => taskController.resume(id)), refresh: () => act(() => taskController.recover()),
    stopResponse: () => act(() => Promise.all(relevantTasks.filter(task => ACTIVE_TASK_STATUSES.has(task.status)).map(task => taskController.cancel(task.id)))),
  };
}
