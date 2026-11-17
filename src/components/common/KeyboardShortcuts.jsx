/**
 * LYRA — Keyboard Shortcuts
 * Global keyboard shortcut handler + cheat sheet modal.
 */

import React, { useEffect, useState, useCallback } from "react";

const SHORTCUTS = [
  { keys: ["⌘/Ctrl", "K"], action: "New conversation", id: "newChat" },
  { keys: ["⌘/Ctrl", "M"], action: "Toggle microphone", id: "toggleMic" },
  { keys: ["⌘/Ctrl", "/"], action: "Focus input", id: "focusInput" },
  { keys: ["⌘/Ctrl", "⇧", "P"], action: "Prompt improver", id: "promptImprover" },
  { keys: ["⌘/Ctrl", "1–9"], action: "Switch work mode", id: "switchMode" },
  { keys: ["Esc"], action: "Close dialogs", id: "escape" },
  { keys: ["⌘/Ctrl", "?"], action: "Show shortcuts", id: "showHelp" },
];

export default function KeyboardShortcuts({
  onNewChat,
  onToggleMic,
  onFocusInput,
  onTogglePromptImprover,
  onSwitchMode,
  modes = [],
}) {
  const [showHelp, setShowHelp] = useState(false);

  const handleKeyDown = useCallback((e) => {
    const isMod = e.metaKey || e.ctrlKey;
    const key = e.key.toLowerCase();

    // Don't trigger shortcuts when typing in inputs (unless it's Escape)
    const isInput = ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName);
    
    if (key === "escape") {
      setShowHelp(false);
      return;
    }

    if (!isMod) return;

    // Ctrl/Cmd + K → New conversation
    if (key === "k") {
      e.preventDefault();
      onNewChat?.();
      return;
    }

    // Ctrl/Cmd + M → Toggle mic
    if (key === "m" && !isInput) {
      e.preventDefault();
      onToggleMic?.();
      return;
    }

    // Ctrl/Cmd + / → Focus input
    if (key === "/") {
      e.preventDefault();
      onFocusInput?.();
      return;
    }

    // Ctrl/Cmd + Shift + P → Prompt improver
    if (key === "p" && e.shiftKey) {
      e.preventDefault();
      onTogglePromptImprover?.();
      return;
    }

    // Ctrl/Cmd + ? → Show shortcuts help
    if (key === "?" || (key === "/" && e.shiftKey)) {
      e.preventDefault();
      setShowHelp(p => !p);
      return;
    }

    // Ctrl/Cmd + 1-6 → Switch mode
    const modeIndex = parseInt(key) - 1;
    if (modeIndex >= 0 && modeIndex < modes.length && !isInput) {
      e.preventDefault();
      onSwitchMode?.(modes[modeIndex].id);
      return;
    }
  }, [onNewChat, onToggleMic, onFocusInput, onTogglePromptImprover, onSwitchMode, modes]);

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  if (!showHelp) return null;

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 10000,
        background: "rgba(6,7,13,0.85)",
        backdropFilter: "blur(16px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        animation: "fade 0.2s ease",
      }}
      onClick={() => setShowHelp(false)}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "rgba(14,16,26,0.95)",
          border: "1px solid rgba(126,184,232,0.1)",
          borderRadius: 20, padding: "36px 40px",
          maxWidth: 420, width: "90%",
          boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
          animation: "fadeUp 0.3s ease",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 28 }}>
          <div>
            <h2 style={{
              fontFamily: "'Cormorant Garamond', Georgia, serif",
              fontSize: "1.5rem", fontWeight: 400, color: "var(--text-primary)",
              marginBottom: 4,
            }}>Keyboard Shortcuts</h2>
            <p style={{ fontSize: "0.68rem", color: "var(--text-muted)", letterSpacing: "0.1em" }}>
              Work faster with shortcuts
            </p>
          </div>
          <button
            onClick={() => setShowHelp(false)}
            style={{
              background: "rgba(126,184,232,0.06)", border: "1px solid rgba(126,184,232,0.1)",
              borderRadius: 8, width: 32, height: 32, color: "var(--text-secondary)",
              cursor: "pointer", fontSize: "0.8rem", display: "flex", alignItems: "center",
              justifyContent: "center", transition: "all 0.2s",
            }}
          >✕</button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {SHORTCUTS.map((s) => (
            <div
              key={s.id}
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "10px 14px", borderRadius: 10,
                background: "rgba(126,184,232,0.02)",
                border: "1px solid rgba(126,184,232,0.04)",
                transition: "all 0.2s",
              }}
            >
              <span style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>{s.action}</span>
              <div style={{ display: "flex", gap: 4 }}>
                {s.keys.map((k, i) => (
                  <span key={i} style={{
                    background: "rgba(126,184,232,0.08)",
                    border: "1px solid rgba(126,184,232,0.12)",
                    borderRadius: 6, padding: "3px 8px",
                    fontSize: "0.65rem", fontWeight: 600,
                    color: "var(--accent)", letterSpacing: "0.05em",
                    fontFamily: "monospace",
                  }}>{k}</span>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div style={{
          marginTop: 20, textAlign: "center",
          fontSize: "0.55rem", color: "var(--text-muted)",
          letterSpacing: "0.15em",
        }}>
          PRESS ESC OR CLICK OUTSIDE TO CLOSE
        </div>
      </div>
    </div>
  );
}
