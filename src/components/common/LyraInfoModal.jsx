import React, { useEffect } from "react";
import { MODES } from "../../utils/constants";

export default function LyraInfoModal({ onClose }) {
  useEffect(() => {
    const closeOnEscape = event => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div role="presentation" onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 2000, background: "rgba(0,0,0,0.7)", display: "grid", placeItems: "center", padding: 24 }}>
      <div role="dialog" aria-modal="true" aria-labelledby="lyra-about-title" onClick={event => event.stopPropagation()} style={{ background: "#121419", border: "1px solid #30333b", borderRadius: 16, padding: 28, width: "100%", maxWidth: 440, color: "#f0f0f3" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <h2 id="lyra-about-title" style={{ margin: 0 }}>About Lyra</h2>
          <button onClick={onClose} aria-label="Close" style={{ background: "transparent", border: 0, color: "inherit", cursor: "pointer", fontSize: 20 }}>×</button>
        </div>
        <p style={{ lineHeight: 1.7 }}>Lyra helps with conversations, writing, research, documents, and code. Desktop mode provides voice, personal memory, and terminal access.</p>
        <p style={{ lineHeight: 1.7, color: "#adb2bf" }}>Conversation history is stored locally. Cloud model requests send the context needed for your request to the selected provider. Personal memories can be reviewed or deleted in Desktop → Memory.</p>
        <p style={{ color: "#adb2bf", marginBottom: 0 }}>{MODES.length} work modes · Version 3.0</p>
      </div>
    </div>
  );
}
