/** Voice capture and playback use the same assistant tasks as text. */
import { useState, useEffect, useRef, useCallback } from 'react';
import { voiceManager } from '../modules/VoiceManager';
export const VOICE_STATES = { IDLE: 'idle', CONNECTING: 'connecting', LISTENING: 'listening', THINKING: 'thinking', SPEAKING: 'speaking', ERROR: 'error' };
export function useRealtimeVoice(options = {}) {
  const [voiceState, setVoiceState] = useState(VOICE_STATES.IDLE);
  const [userTranscript, setUserTranscript] = useState(''); const [assistantText, setAssistantText] = useState('');
  const [audioLevel, setAudioLevel] = useState(0); const [error, setError] = useState('');
  const callbacks = useRef(options); callbacks.current = options;
  const active = useRef(false); const waiting = useRef(false); const currentTask = useRef(null);
  const lastToolCall = [...(options.agent?.agentMessages || [])].reverse().find(message => message.role === 'tool_call')?.confirmation;
  useEffect(() => {
    const handleCommand = async text => {
      if (!active.current || !text.trim()) return;
      voiceManager.stop(false); setUserTranscript(text); setVoiceState(VOICE_STATES.THINKING);
      callbacks.current.onUserTranscript?.(text); waiting.current = true;
      try {
        const accepted = await callbacks.current.onSend?.(text);
        if (!accepted) throw new Error('The backend could not accept your voice request. Your transcript is preserved.');
        currentTask.current = null;
      } catch (failure) { setError(failure.message); waiting.current = false; setVoiceState(VOICE_STATES.ERROR); active.current = false; }
    };
    voiceManager.listener.onCommand(handleCommand);
    voiceManager.onStateChange(state => { if (active.current) setVoiceState(state === 'active' ? VOICE_STATES.LISTENING : state === 'speaking' ? VOICE_STATES.SPEAKING : waiting.current ? VOICE_STATES.THINKING : VOICE_STATES.IDLE); });
    voiceManager.onAudioLevel(setAudioLevel);
    voiceManager.onTranscript(({ interim }) => { if (interim) setUserTranscript(interim); });
    voiceManager.onError(reason => { setError(reason === 'mic-denied' ? 'Microphone access was denied.' : String(reason?.message || reason || 'Voice transcription failed.')); setVoiceState(VOICE_STATES.ERROR); active.current = false; waiting.current = false; });
    voiceManager.setContinuousMode(false);
    return () => { active.current = false; voiceManager.stop(false); voiceManager.listener.onCommand(null); voiceManager.onStateChange(null); voiceManager.onAudioLevel(null); voiceManager.onTranscript(null); voiceManager.onError(null); };
  }, []);
  useEffect(() => {
    if (!waiting.current || !active.current) return;
    const messages = options.agent?.agentMessages || [];
    const response = [...messages].reverse().find(message => message.role === 'assistant' && message.status === 'completed' && message.task_id !== currentTask.current);
    if (!response || options.agent?.isThinking) return;
    currentTask.current = response.task_id; waiting.current = false; setAssistantText(response.content);
    callbacks.current.onAssistantResponse?.(response.content);
    setVoiceState(VOICE_STATES.SPEAKING);
    voiceManager.speak(response.content).catch(failure => { setError(failure.message); setVoiceState(VOICE_STATES.ERROR); active.current = false; }).finally(() => { if (active.current) { active.current = false; setVoiceState(VOICE_STATES.IDLE); } });
  }, [options.agent?.agentMessages, options.agent?.isThinking]);
  const startConversation = useCallback(async () => {
    if (!callbacks.current.agent?.connected) { setError('The backend is disconnected.'); setVoiceState(VOICE_STATES.ERROR); return; }
    setError(''); setUserTranscript(''); setAssistantText(''); active.current = true; waiting.current = false;
    const previous = [...(callbacks.current.agent?.agentMessages || [])].reverse().find(message => message.role === 'assistant'); currentTask.current = previous?.task_id || null;
    setVoiceState(VOICE_STATES.CONNECTING); const started = await voiceManager.startListening();
    if (!active.current) { voiceManager.stop(false); return; }
    if (started) setVoiceState(VOICE_STATES.LISTENING); else { active.current = false; setVoiceState(VOICE_STATES.ERROR); }
  }, []);
  const stopConversation = useCallback(() => {
    active.current = false; waiting.current = false; voiceManager.stop(false); callbacks.current.agent?.stopResponse?.(); setVoiceState(VOICE_STATES.IDLE); setAudioLevel(0);
  }, []);
  return { voiceState, isRealtimeAvailable: !!globalThis.navigator?.mediaDevices, isConnected: !!options.agent?.connected, userTranscript, assistantText, audioLevel, error, lastToolCall: lastToolCall ? { name: lastToolCall.tool, args: lastToolCall.arguments } : null, startConversation, stopConversation, sendTextMessage: text => callbacks.current.onSend?.(text), VOICE_STATES };
}
export default useRealtimeVoice;
