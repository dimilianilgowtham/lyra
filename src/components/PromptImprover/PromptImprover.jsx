/**
 * LYRA — Prompt Improver Component
 * Slide-out panel for enhancing prompts with Simple / Developer / Creative modes.
 */

import React, { useState, useRef, useEffect } from "react";
import { PromptEngine } from "../../modules/PromptEngine";
import { PROMPT_IMPROVEMENT_MODES } from "../../utils/constants";
import "./PromptImprover.css";

export default function PromptImprover({ onApply, onClose }) {
  const [input, setInput] = useState("");
  const [mode, setMode] = useState("simple");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [visible, setVisible] = useState(false);
  const inputRef = useRef(null);
  const engineRef = useRef(new PromptEngine());

  useEffect(() => { setTimeout(() => setVisible(true), 30); inputRef.current?.focus(); }, []);

  const complexity = engineRef.current.analyzeComplexity(input);
  const modeConfig = PROMPT_IMPROVEMENT_MODES.find(m => m.id === mode);

  const handleImprove = async () => {
    if (!input.trim()) return;
    setLoading(true); setError(""); setResult(null);
    try {
      const res = await engineRef.current.improve(input, mode);
      setResult(res);
    } catch (e) {
      setError(e.message || "Failed to improve prompt.");
    } finally {
      setLoading(false);
    }
  };

  const handleApply = () => {
    if (result?.improved) {
      onApply(result.improved);
      handleClose();
    }
  };

  const handleClose = () => {
    setVisible(false);
    setTimeout(onClose, 300);
  };

  return (
    <div className={`prompt-improver-overlay ${visible ? "visible" : ""}`} onClick={handleClose}>
      <div className={`prompt-improver-panel ${visible ? "visible" : ""}`} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="pi-header">
          <div>
            <h3 className="pi-title">Refine Prompt</h3>
            <p className="pi-subtitle">Make your prompt clearer and more effective</p>
          </div>
          <button onClick={handleClose} className="pi-close">✕</button>
        </div>

        {/* Mode Selector */}
        <div className="pi-modes">
          {PROMPT_IMPROVEMENT_MODES.map(m => (
            <button
              key={m.id}
              className={`pi-mode-btn ${mode === m.id ? "active" : ""}`}
              onClick={() => setMode(m.id)}
              style={{ "--mode-color": m.color }}
            >
              <span className="pi-mode-icon">{m.icon}</span>
              <div>
                <div className="pi-mode-label">{m.label}</div>
                <div className="pi-mode-desc">{m.desc}</div>
              </div>
            </button>
          ))}
        </div>

        {/* Input */}
        <div className="pi-input-section">
          <div className="pi-input-header">
            <span>Your Prompt</span>
            <span className="pi-complexity">
              Complexity: <span style={{ color: complexity > 60 ? "#9dd4b0" : complexity > 30 ? "#d4c89a" : "#d4a8c8" }}>{complexity}/100</span>
            </span>
          </div>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Write or paste your prompt…"
            className="pi-textarea"
            rows={4}
          />
          <div className="pi-char-count">{input.length} chars · {input.trim().split(/\s+/).filter(Boolean).length} words</div>
        </div>

        {/* Improve Button */}
        <button
          onClick={handleImprove}
          disabled={!input.trim() || loading}
          className="pi-improve-btn"
          style={{ "--mode-color": modeConfig?.color || "#6b8afd" }}
        >
          {loading ? (
            <><div className="pi-spinner" /> Refining…</>
          ) : (
            <>{modeConfig?.icon} Refine with {modeConfig?.label}</>
          )}
        </button>

        {error && <div className="pi-error">⚠ {error}</div>}

        {/* Result */}
        {result && (
          <div className="pi-result">
            <div className="pi-result-header">
              <span className="pi-result-badge" style={{ color: modeConfig?.color }}>
                {modeConfig?.icon} {modeConfig?.label} Refinement
              </span>
            </div>
            <div className="pi-result-text">{result.improved}</div>
            <div className="pi-result-actions">
              <button onClick={() => { navigator.clipboard.writeText(result.improved); }} className="pi-action-btn">
                ⎘ Copy
              </button>
              <button onClick={handleApply} className="pi-action-btn pi-apply-btn" style={{ "--mode-color": modeConfig?.color }}>
                → Apply
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
