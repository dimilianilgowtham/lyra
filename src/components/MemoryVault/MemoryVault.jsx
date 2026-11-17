import React, { useState, useEffect } from "react";
import { DesktopBridge } from "../../modules/DesktopBridge";
import { Brain, Trash2, CheckCircle2, XCircle, Plus, RefreshCw, X, Shield } from "lucide-react";
import "./MemoryVault.css";

export default function MemoryVault({ isOpen, onClose, userId = "default_user" }) {
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [newFact, setNewFact] = useState("");
  const [newCategory, setNewCategory] = useState("preference");
  const [statusMsg, setStatusMsg] = useState("");

  useEffect(() => {
    if (isOpen) {
      loadMemories();
    }
  }, [isOpen, userId]);

  const loadMemories = async () => {
    setLoading(true);
    try {
      const data = await DesktopBridge.getMemories(userId);
      setMemories(data);
    } catch (e) {
      setStatusMsg("Failed to load memories.");
    } finally {
      setLoading(false);
    }
  };

  const handleAddMemory = async (e) => {
    e.preventDefault();
    if (!newFact.trim()) return;
    try {
      await DesktopBridge.addMemory(newFact.trim(), newCategory, true, userId);
      setNewFact("");
      setStatusMsg("Memory stored with consent.");
      await loadMemories();
      setTimeout(() => setStatusMsg(""), 3000);
    } catch {
      setStatusMsg("Failed to add memory.");
    }
  };

  const handleToggleConsent = async (mem) => {
    try {
      const newConsented = !mem.consented;
      await DesktopBridge.updateMemory(mem.id, { consented: newConsented });
      setMemories(prev => prev.map(m => m.id === mem.id ? { ...m, consented: newConsented } : m));
    } catch {
      setStatusMsg("Failed to update memory.");
    }
  };

  const handleDelete = async (memId) => {
    try {
      await DesktopBridge.deleteMemory(memId);
      setMemories(prev => prev.filter(m => m.id !== memId));
      setStatusMsg("Memory forgotten.");
      setTimeout(() => setStatusMsg(""), 3000);
    } catch {
      setStatusMsg("Failed to delete memory.");
    }
  };

  const handleClearAll = async () => {
    if (!window.confirm("Are you sure you want Lyra to forget all stored memories and preferences?")) {
      return;
    }
    try {
      await DesktopBridge.clearMemories(userId);
      setMemories([]);
      setStatusMsg("All memories cleared.");
      setTimeout(() => setStatusMsg(""), 3000);
    } catch {
      setStatusMsg("Failed to clear memories.");
    }
  };

  if (!isOpen) return null;

  return (
    <div className="memory-vault-overlay" onClick={onClose}>
      <div className="memory-vault-modal" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="mv-header">
          <div className="mv-title">
            <Brain className="mv-icon" size={22} />
            <div>
              <h3>Lyra Memory Vault</h3>
              <p>Review, edit, or revoke consented facts and personal preferences</p>
            </div>
          </div>
          <button className="mv-close-btn" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {/* Status / Feedback Banner */}
        {statusMsg && <div className="mv-status-banner">{statusMsg}</div>}

        {/* Add Memory Form */}
        <form className="mv-add-form" onSubmit={handleAddMemory}>
          <input
            type="text"
            placeholder="Add a preference or fact (e.g. 'I prefer concise answers in Python')..."
            value={newFact}
            onChange={e => setNewFact(e.target.value)}
          />
          <select value={newCategory} onChange={e => setNewCategory(e.target.value)}>
            <option value="preference">Preference</option>
            <option value="habit">Habit</option>
            <option value="identity">Identity</option>
            <option value="goal">Goal</option>
            <option value="fact">Fact</option>
          </select>
          <button type="submit" className="mv-btn-primary">
            <Plus size={16} /> Add
          </button>
        </form>

        {/* Memory List */}
        <div className="mv-list-container">
          {loading ? (
            <div className="mv-loading">
              <RefreshCw className="mv-spin" size={20} /> Loading memories...
            </div>
          ) : memories.length === 0 ? (
            <div className="mv-empty">
              <Shield size={32} />
              <p>No memories stored yet. Lyra only learns facts with your explicit consent.</p>
            </div>
          ) : (
            <div className="mv-items">
              {memories.map(mem => (
                <div key={mem.id} className={`mv-item ${!mem.consented ? "mv-item-disabled" : ""}`}>
                  <div className="mv-item-content">
                    <span className="mv-badge">{mem.category}</span>
                    <p>{mem.fact}</p>
                    <span className="mv-time">Updated: {new Date(mem.updated_at).toLocaleDateString()}</span>
                  </div>
                  <div className="mv-item-actions">
                    <button
                      className={`mv-toggle-btn ${mem.consented ? "mv-consented" : "mv-revoked"}`}
                      onClick={() => handleToggleConsent(mem)}
                      title={mem.consented ? "Click to pause consent" : "Click to grant consent"}
                    >
                      {mem.consented ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                      <span>{mem.consented ? "Consented" : "Paused"}</span>
                    </button>
                    <button
                      className="mv-delete-btn"
                      onClick={() => handleDelete(mem.id)}
                      title="Forget this memory"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="mv-footer">
          <span className="mv-count">{memories.length} total facts in vault</span>
          {memories.length > 0 && (
            <button className="mv-btn-danger" onClick={handleClearAll}>
              <Trash2 size={14} /> Forget All
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
