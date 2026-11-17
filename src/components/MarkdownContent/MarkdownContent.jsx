/**
 * LYRA — Markdown Content Renderer
 * Renders AI responses as sanitized, styled HTML from markdown.
 */

import React from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";

marked.setOptions({ breaks: true, gfm: true });

export default function MarkdownContent({ content, color = "#6b8afd" }) {
  const html = DOMPurify.sanitize(marked.parse(content || ""));
  return (
    <div
      className="lyra-markdown"
      dangerouslySetInnerHTML={{ __html: html }}
      style={{
        fontSize: "0.875rem", lineHeight: 1.9, color: "rgba(240,242,250,0.95)",
        "--md-accent": color,
      }}
    />
  );
}
