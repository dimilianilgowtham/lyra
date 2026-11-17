/**
 * LYRA — Model Selector (Milestone 2: Multi-Model Intelligence)
 * 
 * Premium glassmorphic dropdown that lets users browse and switch
 * between all available AI models. Grouped by provider with
 * availability indicators, strength tags, and smooth animations.
 * 
 * Props:
 *   isOpen           — whether the dropdown is visible
 *   onClose          — close the dropdown
 *   selectedModel    — currently selected model ID (null = auto)
 *   onSelectModel    — callback(modelId | null)
 *   activeMode       — current work mode (for auto-routing display)
 *   modeColor        — current mode accent color
 */

import React, { useEffect, useRef, useMemo } from "react";
import { ModelRouter } from "../../modules/ModelRouter";

export default function ModelSelector({
  isOpen,
  onClose,
  selectedModel,
  onSelectModel,
  activeMode,
  modeColor, health,
}) {
  const panelRef = useRef(null);

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return;
    const handleClick = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        onClose();
      }
    };
    // Delay to prevent the opening click from immediately closing
    const timer = setTimeout(() => {
      document.addEventListener("mousedown", handleClick);
    }, 10);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", handleClick);
    };
  }, [isOpen, onClose]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [isOpen, onClose]);

  // Get model data from registry
  const groups = useMemo(() => ModelRouter.getModelsGrouped(), [isOpen, health]);

  // Get the auto-routed model for current mode
  const autoConfig = useMemo(() => ModelRouter.getConfig(activeMode), [activeMode]);

  if (!isOpen) return null;

  const isAuto = selectedModel === null;

  return (
    <div
      ref={panelRef}
      style={{
        position: "absolute",
        top: "calc(100% + 8px)",
        right: 0,
        width: 340,
        maxHeight: "70vh",
        overflowY: "auto",
        background: "rgba(8, 8, 14, 0.97)",
        border: "1px solid rgba(255, 255, 255, 0.08)",
        borderRadius: 16,
        padding: "8px",
        boxShadow: "0 20px 60px rgba(0, 0, 0, 0.7), 0 0 40px rgba(255, 42, 42, 0.04)",
        backdropFilter: "blur(40px)",
        WebkitBackdropFilter: "blur(40px)",
        zIndex: 200,
        animation: "fadeUp 0.18s ease-out",
      }}
      className="lyra-model-selector"
    >
      {/* Header */}
      <div style={{
        padding: "10px 12px 8px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        <span style={{
          fontSize: "0.52rem",
          letterSpacing: "0.18em",
          color: "rgba(240, 240, 243, 0.3)",
          fontWeight: 700,
          fontFamily: "'Orbitron', sans-serif",
        }}>
          MODEL SELECTOR
        </span>
        <span style={{
          fontSize: "0.48rem",
          color: "rgba(240, 240, 243, 0.2)",
          fontFamily: "'Inter', sans-serif",
        }}>
          {groups.reduce((sum, g) => sum + g.models.filter(m => m.isAvailable).length, 0)} configured
        </span>
      </div>

      {/* Auto Option */}
      <button
        onClick={() => { onSelectModel(null); onClose(); }}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 12px",
          borderRadius: 12,
          border: isAuto ? "1px solid rgba(255, 42, 42, 0.2)" : "1px solid transparent",
          background: isAuto ? "rgba(255, 42, 42, 0.06)" : "transparent",
          cursor: "pointer",
          textAlign: "left",
          transition: "all 0.15s ease",
          marginBottom: 4,
        }}
        onMouseEnter={(e) => {
          if (!isAuto) {
            e.currentTarget.style.background = "rgba(255, 255, 255, 0.03)";
            e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.06)";
          }
        }}
        onMouseLeave={(e) => {
          if (!isAuto) {
            e.currentTarget.style.background = "transparent";
            e.currentTarget.style.borderColor = "transparent";
          }
        }}
      >
        {/* Auto Icon */}
        <div style={{
          width: 32,
          height: 32,
          borderRadius: 10,
          background: isAuto
            ? "linear-gradient(135deg, rgba(255, 42, 42, 0.15), rgba(0, 229, 255, 0.1))"
            : "rgba(255, 255, 255, 0.04)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "0.85rem",
          flexShrink: 0,
          transition: "all 0.2s",
        }}>
          ✦
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: "0.76rem",
            fontWeight: isAuto ? 600 : 500,
            color: isAuto ? "#f0f0f3" : "rgba(240, 240, 243, 0.6)",
            fontFamily: "'Inter', sans-serif",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}>
            Auto
            <span style={{
              fontSize: "0.48rem",
              letterSpacing: "0.1em",
              color: isAuto ? "rgba(255, 42, 42, 0.7)" : "rgba(240, 240, 243, 0.25)",
              fontFamily: "'Orbitron', sans-serif",
              fontWeight: 600,
            }}>
              BACKEND
            </span>
          </div>
          <div style={{
            fontSize: "0.6rem",
            color: "rgba(240, 240, 243, 0.3)",
            marginTop: 2,
            fontFamily: "'Inter', sans-serif",
          }}>
            {autoConfig.label} via {autoConfig.providerName}
          </div>
        </div>

        {isAuto && (
          <div style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: "#FF2A2A",
            boxShadow: "0 0 8px rgba(255, 42, 42, 0.4)",
            flexShrink: 0,
          }} />
        )}
      </button>

      {/* Divider */}
      <div style={{
        height: 1,
        background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent)",
        margin: "4px 12px 6px",
      }} />

      {/* Provider Groups */}
      {groups.map((group) => (
        <div key={group.provider} style={{ marginBottom: 4 }}>
          {/* Provider Header */}
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 12px 4px",
          }}>
            <span style={{ fontSize: "0.7rem" }}>{group.icon}</span>
            <span style={{
              fontSize: "0.5rem",
              letterSpacing: "0.14em",
              color: group.hasKey ? group.color : "rgba(240, 240, 243, 0.2)",
              fontWeight: 700,
              fontFamily: "'Orbitron', sans-serif",
              textTransform: "uppercase",
              opacity: group.hasKey ? 1 : 0.5,
            }}>
              {group.providerLabel}
            </span>
            {!group.hasKey && (
              <span style={{
                fontSize: "0.48rem",
                color: "rgba(255, 160, 80, 0.6)",
                fontFamily: "'Inter', sans-serif",
                marginLeft: "auto",
              }}>
                Not configured in backend
              </span>
            )}
          </div>

          {/* Model Rows */}
          {group.models.map((model) => {
            const isSelected = selectedModel === model.id;
            const isDisabled = !model.isAvailable;

            return (
              <button
                key={model.id}
                onClick={() => {
                  if (isDisabled) return;
                  onSelectModel(model.id);
                  onClose();
                }}
                disabled={isDisabled}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 12px",
                  borderRadius: 10,
                  border: isSelected ? `1px solid ${model.providerColor}30` : "1px solid transparent",
                  background: isSelected ? `${model.providerColor}0A` : "transparent",
                  cursor: isDisabled ? "not-allowed" : "pointer",
                  textAlign: "left",
                  transition: "all 0.12s ease",
                  opacity: isDisabled ? 0.35 : 1,
                }}
                onMouseEnter={(e) => {
                  if (!isSelected && !isDisabled) {
                    e.currentTarget.style.background = "rgba(255, 255, 255, 0.03)";
                    e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.04)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isSelected && !isDisabled) {
                    e.currentTarget.style.background = "transparent";
                    e.currentTarget.style.borderColor = "transparent";
                  }
                }}
              >
                {/* Model Icon */}
                <div style={{
                  width: 28,
                  height: 28,
                  borderRadius: 8,
                  background: isSelected
                    ? `${model.providerColor}18`
                    : "rgba(255, 255, 255, 0.03)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "0.72rem",
                  flexShrink: 0,
                  transition: "all 0.15s",
                }}>
                  {model.icon}
                </div>

                {/* Model Info */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: "0.72rem",
                    fontWeight: isSelected ? 600 : 450,
                    color: isSelected ? "#f0f0f3" : "rgba(240, 240, 243, 0.55)",
                    fontFamily: "'Inter', sans-serif",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                  }}>
                    {model.label}
                    {model.contextWindow && (
                      <span style={{
                        fontSize: "0.45rem",
                        color: isSelected ? model.providerColor : "rgba(240, 240, 243, 0.2)",
                        fontFamily: "'Orbitron', sans-serif",
                        fontWeight: 600,
                        letterSpacing: "0.05em",
                      }}>
                        {model.contextWindow}
                      </span>
                    )}
                  </div>
                  <div style={{
                    fontSize: "0.56rem",
                    color: "rgba(240, 240, 243, 0.25)",
                    marginTop: 1,
                    fontFamily: "'Inter', sans-serif",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}>
                    {model.description}
                  </div>

                  {/* Strength Tags */}
                  {isSelected && model.strengths && (
                    <div style={{
                      display: "flex",
                      gap: 4,
                      marginTop: 4,
                      flexWrap: "wrap",
                    }}>
                      {model.strengths.slice(0, 3).map((s) => (
                        <span
                          key={s}
                          style={{
                            fontSize: "0.44rem",
                            padding: "2px 6px",
                            borderRadius: 4,
                            background: `${model.providerColor}10`,
                            color: `${model.providerColor}CC`,
                            fontWeight: 600,
                            fontFamily: "'Inter', sans-serif",
                            letterSpacing: "0.04em",
                          }}
                        >
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Selection indicator */}
                {isSelected ? (
                  <div style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: model.providerColor,
                    boxShadow: `0 0 8px ${model.providerColor}60`,
                    flexShrink: 0,
                  }} />
                ) : !isDisabled ? (
                  <div style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    border: "1px solid rgba(255, 255, 255, 0.1)",
                    flexShrink: 0,
                  }} />
                ) : null}
              </button>
            );
          })}
        </div>
      ))}

      {/* Footer hint */}
      <div style={{
        padding: "8px 12px 6px",
        borderTop: "1px solid rgba(255, 255, 255, 0.04)",
        marginTop: 4,
      }}>
        <div style={{
          fontSize: "0.5rem",
          color: "rgba(240, 240, 243, 0.2)",
          fontFamily: "'Inter', sans-serif",
          textAlign: "center",
        }}>
          Availability is reported by your backend
        </div>
      </div>
    </div>
  );
}
