/**
 * LYRA — Tool Confirmation Card v2.0
 * Renders inline approval cards for pending tool calls in the chat area.
 * Dark terminal aesthetic matching Lyra's HUD design language.
 *
 * v2.0: Expanded to support Odysseus's full 20+ tool vocabulary
 * with syntax-highlighted previews for code tools and structured
 * previews for communication/memory tools.
 */

import React from "react";

// ── Tool Metadata (Odysseus full vocabulary) ─────────────────────────────────

const TOOL_ICONS = {
  // Filesystem
  read_file: "📄", write_file: "✏️", edit_file: "🔧", list_directory: "📂",
  list_dir: "📂", grep: "🔍",
  // Execution
  bash: "⚡", execute_terminal_command: "⚡", execute_command: "⚡", python: "🐍",
  // Web
  web_search: "🌐", fetch_page: "📡",
  // Communication
  send_email: "📧", manage_calendar: "📅",
  // Memory
  store_memory: "🧠", recall_memory: "💭", memory_save: "🧠", memory_search: "💭",
  // Planning
  update_plan: "📋", ask_user: "❓",
  // Desktop
  take_screenshot: "📸", click_at: "🖱️", type_text: "⌨️",
  // Tasks
  manage_tasks: "⏰", schedule_task: "⏰",
};

const TOOL_LABELS = {
  read_file: "Read File", write_file: "Write File", edit_file: "Edit File",
  list_directory: "List Directory", list_dir: "List Directory", grep: "Search Files",
  bash: "Shell Command", execute_terminal_command: "Terminal Command", execute_command: "Terminal Command",
  python: "Python Script",
  web_search: "Web Search", fetch_page: "Fetch Page",
  send_email: "Send Email", manage_calendar: "Calendar",
  store_memory: "Store Memory", recall_memory: "Recall Memory",
  memory_save: "Save Memory", memory_search: "Search Memory",
  update_plan: "Update Plan", ask_user: "Ask User",
  take_screenshot: "Screenshot", click_at: "Mouse Click", type_text: "Type Text",
  manage_tasks: "Manage Tasks", schedule_task: "Schedule Task",
};

const TOOL_RISK = {
  // High risk — modifies system state
  bash: "high", execute_terminal_command: "high", python: "high",
  write_file: "high", edit_file: "high", send_email: "high",
  // Medium risk — interacts with external services
  web_search: "medium", fetch_page: "medium", manage_calendar: "medium",
  click_at: "medium", type_text: "medium", manage_tasks: "medium",
  schedule_task: "medium", update_plan: "medium",
  // Low risk — read-only
  read_file: "low", list_directory: "low", list_dir: "low", grep: "low",
  take_screenshot: "low", store_memory: "low", recall_memory: "low",
  memory_save: "low", memory_search: "low", ask_user: "low",
};

const RISK_COLORS = {
  high:   { bg: "rgba(255,68,68,0.12)", text: "#ff6666", border: "rgba(255,68,68,0.25)", badge: "#ff4444", badgeText: "#fff" },
  medium: { bg: "rgba(255,153,0,0.08)", text: "#ffbb44", border: "rgba(255,153,0,0.2)", badge: "#ff9900", badgeText: "#000" },
  low:    { bg: "rgba(0,204,102,0.06)", text: "#44ee88", border: "rgba(0,204,102,0.15)", badge: "#00cc66", badgeText: "#000" },
};

// ── Smart Argument Formatting ────────────────────────────────────────────────

function formatArgs(tool, args) {
  if (!args || !Object.keys(args).length) return "(no arguments)";
  if (["bash", "execute_command", "execute_terminal_command"].includes(tool) && args.command) return `$ ${args.command}${args.cwd ? `\nWorking directory: ${args.cwd}` : ""}`;
  return JSON.stringify(args, null, 2);
}

// ── Component ────────────────────────────────────────────────────────────────

export default function ToolConfirmationCard({ confirmation, onConfirm, onDeny, resolved, approved }) {
  const { request_id, tool, arguments: args } = confirmation;
  const icon = TOOL_ICONS[tool] || "🔧";
  const label = TOOL_LABELS[tool] || tool;
  const reportedRisk = String(confirmation.risk_tier || "").toLowerCase();
  const risk = ["low", "medium", "high"].includes(reportedRisk) ? reportedRisk : TOOL_RISK[tool] || "medium";
  const colors = RISK_COLORS[risk];
  // Resolved state
  if (resolved) {
    return (
      <div style={{
        ...styles.card,
        borderLeftColor: approved ? "#00cc66" : "#ff4444",
        opacity: 0.6,
      }}>
        <div style={styles.header}>
          <span style={styles.icon}>{icon}</span>
          <span style={{ ...styles.toolName, color: approved ? "#44ee88" : "#ff6666" }}>
            {label}
          </span>
          <span style={{
            ...styles.riskBadge,
            background: approved ? "rgba(0,204,102,0.15)" : "rgba(255,68,68,0.15)",
            color: approved ? "#44ee88" : "#ff6666",
          }}>
            {approved ? "✓ APPROVED" : "✕ DENIED"}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      ...styles.card,
      background: colors.bg,
      borderColor: colors.border,
    }}>
      {/* Header */}
      <div style={styles.header}>
        <span style={styles.icon}>{icon}</span>
        <div style={styles.titleGroup}>
          <span style={{ ...styles.toolName, color: colors.text }}>{label}</span>
          <span style={{
            ...styles.riskBadge,
            background: colors.badge,
            color: colors.badgeText,
          }}>
            {risk.toUpperCase()} RISK
          </span>
        </div>
        <span style={styles.timer}>Approval required</span>
      </div>

      {confirmation.impact_summary && <p style={{ fontSize: "0.78rem", lineHeight: 1.6, color: "#d6d4df" }}>{confirmation.impact_summary}</p>}
      {/* Arguments preview */}
      <div style={styles.argsBox}>
        <pre style={styles.args}>{formatArgs(tool, args)}</pre>
      </div>

      {/* Action buttons */}
      <div style={styles.actions}>
        <button
          style={{ ...styles.btn, ...styles.denyBtn }}
          onClick={() => onDeny(request_id)}
          onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,68,68,0.2)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,68,68,0.08)"; }}
        >
          ✕ Deny
        </button>
        <button
          style={{ ...styles.btn, ...styles.approveBtn }}
          onClick={() => onConfirm(request_id, true)}
          onMouseEnter={(e) => { e.currentTarget.style.background = "#9b81ff"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "#7b61ff"; }}
        >
          ✓ Allow
        </button>
      </div>
    </div>
  );
}

// ── Styles ──────────────────────────────────────────────────────────────────

const styles = {
  card: {
    background: "rgba(123,97,255,0.04)",
    border: "1px solid rgba(123,97,255,0.12)",
    borderLeft: "3px solid #7b61ff",
    borderRadius: 12,
    padding: "16px 18px",
    margin: "8px 0",
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Inter', monospace",
    maxWidth: "100%",
    animation: "fadeUp 0.3s ease-out both",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 12,
  },
  icon: {
    fontSize: "18px",
    width: 28,
    height: 28,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "rgba(123,97,255,0.08)",
    borderRadius: 8,
  },
  titleGroup: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flex: 1,
  },
  toolName: {
    color: "#e0e0e0",
    fontSize: "0.78rem",
    fontWeight: 600,
    fontFamily: "'Inter', sans-serif",
  },
  riskBadge: {
    fontSize: "0.55rem",
    fontWeight: 700,
    padding: "2px 8px",
    borderRadius: 4,
    textTransform: "uppercase",
    letterSpacing: "0.8px",
    fontFamily: "'Orbitron', 'Inter', sans-serif",
  },
  timer: {
    fontSize: "0.65rem",
    color: "rgba(255,255,255,0.3)",
    fontFamily: "'Orbitron', monospace",
    fontWeight: 600,
  },
  argsBox: {
    background: "rgba(5,5,5,0.5)",
    border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: 8,
    padding: "10px 14px",
    marginBottom: 14,
    overflow: "hidden",
  },
  args: {
    color: "rgba(240,240,243,0.6)",
    fontSize: "0.7rem",
    margin: 0,
    whiteSpace: "pre-wrap",
    wordBreak: "break-all",
    lineHeight: 1.6,
    maxHeight: 320, overflowY: "auto",
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
  },
  actions: {
    display: "flex",
    gap: 8,
    justifyContent: "flex-end",
  },
  btn: {
    padding: "7px 20px",
    borderRadius: 8,
    border: "none",
    cursor: "pointer",
    fontSize: "0.72rem",
    fontWeight: 700,
    fontFamily: "'Inter', sans-serif",
    letterSpacing: "0.3px",
    transition: "all 0.15s ease",
  },
  denyBtn: {
    background: "rgba(255,68,68,0.08)",
    color: "#ff6666",
    border: "1px solid rgba(255,68,68,0.15)",
  },
  approveBtn: {
    background: "#7b61ff",
    color: "#fff",
    boxShadow: "0 2px 12px rgba(123,97,255,0.25)",
  },
};
