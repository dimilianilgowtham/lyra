/**
 * LYRA — Realtime Voice Panel v1.0
 *
 * Floating voice conversation UI with:
 *   - Animated orb that pulses with audio
 *   - State indicators: IDLE → CONNECTING → LISTENING → THINKING → SPEAKING
 *   - Live transcripts (user + assistant)
 *   - Tool call notifications
 *   - One-click start/stop
 */

import React, { useState, useCallback } from "react";
import { useRealtimeVoice } from "../../hooks/useRealtimeVoice";
import "./RealtimeVoice.css";

const STATE_CONFIG = {
  idle:       { label: "Start Voice",   color: "#6366f1", icon: "🎙️",  animate: false },
  connecting: { label: "Connecting...", color: "#f59e0b", icon: "⏳",  animate: true  },
  listening:  { label: "Listening",     color: "#22c55e", icon: "👂",  animate: true  },
  thinking:   { label: "Thinking...",   color: "#a855f7", icon: "🧠",  animate: true  },
  speaking:   { label: "Speaking",      color: "#3b82f6", icon: "🔊",  animate: true  },
  error:      { label: "Error",         color: "#ef4444", icon: "⚠️",  animate: false },
};

export default function RealtimeVoicePanel({ onTranscript, onSend, agent }) {
  const {
    voiceState,
    isRealtimeAvailable,
    userTranscript,
    assistantText,
    audioLevel,
    error,
    lastToolCall,
    startConversation,
    stopConversation,
    VOICE_STATES,
  } = useRealtimeVoice({
    onSend, agent,
    onUserTranscript: (text) => {
      if (onTranscript) onTranscript(text);
    },

  });

  const [isExpanded, setIsExpanded] = useState(false);

  const config = STATE_CONFIG[voiceState] || STATE_CONFIG.idle;
  const isActive = voiceState !== VOICE_STATES.IDLE && voiceState !== VOICE_STATES.ERROR;

  const handleToggle = useCallback(() => {
    if (isActive) {
      stopConversation();
      setIsExpanded(false);
    } else {
      startConversation();
      setIsExpanded(true);
    }
  }, [isActive, startConversation, stopConversation]);

  // Don't render if Realtime API isn't available
  if (!isRealtimeAvailable) return null;

  return (
    <div className={`rtv-panel ${isExpanded ? "expanded" : ""}`}>
      {/* Expanded conversation view */}
      {isExpanded && (
        <div className="rtv-conversation">
          {/* Header */}
          <div className="rtv-header">
            <div className="rtv-header-left">
              <span className="rtv-dot" style={{ backgroundColor: config.color }} />
              <span className="rtv-status">{config.label}</span>
            </div>
            <button className="rtv-close" onClick={() => { stopConversation(); setIsExpanded(false); }}>
              ✕
            </button>
          </div>

          {/* Orb */}
          <div className="rtv-orb-container">
            <div
              className={`rtv-orb ${config.animate ? "active" : ""}`}
              style={{
                "--orb-color": config.color,
                "--orb-scale": 1 + audioLevel * 0.4,
                "--orb-glow": `0 0 ${20 + audioLevel * 60}px ${config.color}80`,
              }}
            />
          </div>

          {/* Transcripts */}
          <div className="rtv-transcripts">
            {userTranscript && (
              <div className="rtv-transcript user">
                <span className="rtv-label">You</span>
                <p>{userTranscript}</p>
              </div>
            )}
            {assistantText && (
              <div className="rtv-transcript assistant">
                <span className="rtv-label">Lyra</span>
                <p>{assistantText}</p>
              </div>
            )}
            {lastToolCall && (
              <div className="rtv-tool-call">
                🔧 {lastToolCall.name}({Object.values(lastToolCall.args || {}).join(", ")})
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="rtv-error">{error}</div>
          )}
        </div>
      )}

      {/* Main mic button */}
      <button
        className={`rtv-mic-btn ${isActive ? "active" : ""}`}
        onClick={handleToggle}
        style={{ "--btn-color": config.color }}
        title={isActive ? "Stop voice request" : "Start local voice request"}
      >
        <div className="rtv-mic-inner">
          {isActive ? (
            <div className="rtv-waves">
              {[0, 1, 2, 3, 4].map(i => (
                <div
                  key={i}
                  className="rtv-wave-bar"
                  style={{
                    height: `${8 + audioLevel * 80 * (0.3 + i * 0.15)}%`,
                    animationDelay: `${i * 0.08}s`,
                  }}
                />
              ))}
            </div>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
              <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
            </svg>
          )}
        </div>
        {isActive && <div className="rtv-pulse-ring" style={{ borderColor: config.color }} />}
      </button>
    </div>
  );
}
