import React, { useState, useEffect, useRef, useCallback } from 'react';
import { voiceEngine } from '../../modules/VoiceEngine';
import { VOICE_LANGUAGES } from '../../utils/constants';
import './VoiceAssistant.css';

const BUSY = new Set(['requesting', 'listening', 'speech_detected', 'transcribing']);
export default function VoiceAssistant({ onTranscript, language = 'en-US', onLanguageChange, disabled = false }) {
  const [state, setState] = useState('idle');
  const [audioLevel, setAudioLevel] = useState(0);
  const [error, setError] = useState('');
  const mounted = useRef(false);
  const callback = useRef(onTranscript); callback.current = onTranscript;
  const listening = state === 'listening' || state === 'speech_detected';
  const busy = BUSY.has(state);
  const supported = voiceEngine.isSTTSupported();
  const currentLang = VOICE_LANGUAGES.find(item => item.code === language) || VOICE_LANGUAGES[0];

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; voiceEngine.stopListening(false); };
  }, []);
  useEffect(() => {
    if (disabled) { voiceEngine.stopListening(false); setState('idle'); setAudioLevel(0); }
  }, [disabled]);

  const toggle = useCallback(async () => {
    if (disabled) return;
    if (listening) { voiceEngine.stopListening(true); return; }
    if (busy) { voiceEngine.stopListening(false); setState('idle'); return; }
    setError('');
    if (!supported) { setError('Microphone recording is unavailable. Use Lyra on localhost or its desktop app and allow microphone access.'); return; }
    setState('requesting');
    await voiceEngine.startListening(language, {
      onStateChange: next => { if (mounted.current) setState(next); },
      onAudioLevel: level => { if (mounted.current) setAudioLevel(level); },
      onResult: ({ final, isFinal }) => { if (mounted.current && isFinal && final) callback.current?.(final); },
      onError: reason => { if (mounted.current) { setError(typeof reason === 'string' ? reason : reason.message); setState('error'); } },
    });
  }, [disabled, listening, busy, supported, language]);

  const label = listening ? 'Stop recording and transcribe' : state === 'transcribing' ? 'Cancel transcription' : state === 'requesting' ? 'Cancel microphone request' : `Start voice input (${currentLang.label})`;
  return <div className="voice-assistant">
    <select className="va-language-select" aria-label="Voice language" value={language} onChange={event => onLanguageChange?.(event.target.value)} disabled={disabled || busy}>
      {VOICE_LANGUAGES.map(item => <option key={item.code} value={item.code}>{item.flag} {item.label}</option>)}
    </select>
    <button type="button" className={`va-mic-btn ${listening ? 'listening' : ''} ${state === 'transcribing' ? 'transcribing' : ''}`} disabled={disabled} onClick={toggle} aria-label={label} title={label} aria-pressed={listening}>
      {listening ? <span className="va-level-meter" aria-hidden="true"><span style={{ height: `${Math.max(12, audioLevel * 100)}%` }} /></span> : busy ? <span aria-hidden="true">■</span> : <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z" /></svg>}
    </button>
    {busy && <div className="va-interim" role="status" aria-live="polite">{state === 'requesting' ? 'Allow microphone access…' : state === 'transcribing' ? 'Transcribing recording… Click to cancel.' : 'Recording · click stop to transcribe.'}</div>}
    {error && <div className="va-error" role="alert"><span>{error}</span><button type="button" aria-label="Dismiss voice error" onClick={() => setError('')}>×</button></div>}
  </div>;
}
