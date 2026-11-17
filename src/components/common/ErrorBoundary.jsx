/**
 * LYRA — Error Boundary (HUD Theme)
 * Catches render errors and shows a graceful recovery UI.
 */

import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("Lyra ErrorBoundary:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          minHeight: "100vh", background: "#050505",
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          fontFamily: "'Inter', system-ui, sans-serif", color: "#f0f0f3",
        }}>
          <h2 style={{
            fontFamily: "'Orbitron', sans-serif",
            fontSize: "1rem", fontWeight: 600, marginBottom: 12,
            color: "rgba(240,240,243,0.9)", letterSpacing: "0.15em",
          }}>
            SYSTEM ERROR
          </h2>
          <p style={{
            fontSize: "0.88rem", color: "rgba(240,240,243,0.3)",
            maxWidth: 400, textAlign: "center", lineHeight: 1.8, marginBottom: 28,
          }}>
            An error occurred in the neural interface. Reloading should fix this.
          </p>
          <div style={{
            fontSize: "0.72rem", color: "rgba(255,42,42,0.5)",
            background: "rgba(255,42,42,0.04)", border: "1px solid rgba(255,42,42,0.1)",
            borderRadius: 12, padding: "10px 16px", maxWidth: 500,
            marginBottom: 24, wordBreak: "break-word",
          }}>
            {this.state.error?.message || "Unknown error"}
          </div>
          <button
            onClick={() => { this.setState({ hasError: false, error: null }); window.location.reload(); }}
            style={{
              background: "#FF2A2A",
              border: "none", borderRadius: 12, padding: "12px 32px",
              color: "#050505", fontSize: "0.88rem", fontWeight: 700,
              cursor: "pointer", letterSpacing: "0.05em",
              transition: "all 0.15s ease-out",
              boxShadow: "0 0 20px rgba(255,42,42,0.2)",
            }}
            onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.boxShadow = "0 4px 24px rgba(255,42,42,0.35)"; }}
            onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "0 0 20px rgba(255,42,42,0.2)"; }}
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
