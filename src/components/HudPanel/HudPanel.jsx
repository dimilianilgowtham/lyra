/**
 * LYRA — HUD Panel (Framer Motion)
 * Exact port of lyra_design Panel with slide-in animation and glassmorphism
 */

import React from "react";
import { motion } from "framer-motion";

export default function HudPanel({ children, isOpen, position = "right", title, onClose }) {
  if (!isOpen) return null;
  const variants = {
    hidden: {
      x: position === "right" ? 400 : position === "left" ? -400 : 0,
      y: position === "bottom" ? 300 : position === "top" ? -300 : 0,
      opacity: 0,
    },
    visible: {
      x: 0,
      y: 0,
      opacity: 1,
    },
  };

  const positionStyle = {
    top: position === "right" || position === "left" ? 80 : position === "top" ? 20 : undefined,
    bottom: position === "right" || position === "left" ? 80 : position === "bottom" ? 20 : undefined,
    [position]: 20,
    width: position === "right" || position === "left" ? 360 : "calc(100% - 40px)",
    maxHeight: position === "right" || position === "left" ? "calc(100% - 160px)" : 400,
  };

  return (
    <motion.div
      style={{
        position: "fixed",
        zIndex: 40,
        borderRadius: 16,
        overflow: "hidden",
        background: "rgba(255,255,255,0.08)",
        backdropFilter: "blur(24px)",
        WebkitBackdropFilter: "blur(24px)",
        border: "1px solid rgba(255,255,255,0.12)",
        boxShadow: "0 16px 48px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.08)",
        pointerEvents: isOpen ? "auto" : "none",
        ...positionStyle,
      }}
      initial="hidden"
      animate={isOpen ? "visible" : "hidden"}
      variants={variants}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      {title && (
        <div style={{
          padding: "16px 20px",
          borderBottom: "1px solid rgba(255,255,255,0.1)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}>
          <h3 style={{
            fontFamily: "'Orbitron', sans-serif",
            fontSize: "0.8rem",
            fontWeight: 600,
            letterSpacing: "0.12em",
            color: "rgba(255,255,255,0.95)",
            textTransform: "uppercase",
            margin: 0,
          }}>
            {title}
          </h3>
          {onClose && (
            <button
              onClick={onClose}
              style={{
                background: "none", border: "none", cursor: "pointer",
                padding: "4px 8px", borderRadius: 6,
                color: "rgba(255,255,255,0.4)",
                fontSize: "0.8rem",
                transition: "all 0.15s",
              }}
              onMouseEnter={e => { e.currentTarget.style.color = "rgba(255,255,255,0.8)"; e.currentTarget.style.background = "rgba(255,255,255,0.1)"; }}
              onMouseLeave={e => { e.currentTarget.style.color = "rgba(255,255,255,0.4)"; e.currentTarget.style.background = "none"; }}
            >
              ✕
            </button>
          )}
        </div>
      )}
      <div style={{
        padding: 20,
        overflowY: "auto",
        maxHeight: "calc(100% - 60px)",
        msOverflowStyle: "none",
        scrollbarWidth: "none",
      }}>
        {children}
      </div>
    </motion.div>
  );
}
