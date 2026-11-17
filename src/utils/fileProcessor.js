/**
 * LYRA — File Processing Utilities v2.0
 * Handles reading and parsing uploaded files.
 *
 * Supported formats:
 * - PDF (.pdf) — via pdf.js
 * - Word (.docx) — via mammoth
 * - Excel (.xlsx, .xls) — via xlsx/SheetJS
 * - Plain text (.txt, .md, .csv, .json, .js, .py, .html, .css, etc.)
 */

import * as mammoth from "mammoth";
import { SUPPORTED_FILE_TYPES } from "./constants";

/**
 * Read a file and return its text content.
 * Routes to the appropriate parser based on file extension.
 */
export async function readFileAsText(file) {
  const name = file.name.toLowerCase();

  // ── PDF files ──────────────────────────────────────────────────────────────
  if (name.endsWith(".pdf")) {
    return await readPDF(file);
  }

  // ── Word documents (.docx) ─────────────────────────────────────────────────
  if (name.endsWith(".docx")) {
    const buf = await file.arrayBuffer();
    const result = await mammoth.extractRawText({ arrayBuffer: buf });
    return `[Document: ${file.name}]\n\n${result.value}`;
  }

  // ── Excel spreadsheets (.xlsx, .xls) ───────────────────────────────────────
  if (name.endsWith(".xlsx") || name.endsWith(".xls")) {
    return await readExcel(file);
  }

  // ── Everything else — read as plain text ───────────────────────────────────
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => resolve(`[File: ${file.name}]\n\n${e.target.result}`);
    reader.onerror = reject;
    reader.readAsText(file);
  });
}

/**
 * Read PDF using pdf.js (pdfjs-dist).
 * Extracts text from all pages.
 */
async function readPDF(file) {
  try {
    // Dynamic import to keep initial bundle smaller
    const pdfjsLib = await import("pdfjs-dist");

    // Set worker source (use CDN worker for reliability)
    pdfjsLib.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.mjs`;

    const arrayBuffer = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;

    const pages = [];
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const textContent = await page.getTextContent();
      const pageText = textContent.items
        .map(item => item.str)
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();

      if (pageText) {
        pages.push(`--- Page ${i} ---\n${pageText}`);
      }
    }

    const fullText = pages.join("\n\n");
    if (!fullText.trim()) {
      return `[PDF: ${file.name}]\n\n(This PDF appears to be image-based or empty. Text extraction was not possible. Try a text-based PDF.)`;
    }

    return `[PDF: ${file.name} — ${pdf.numPages} pages]\n\n${fullText}`;
  } catch (err) {
    console.error("PDF reading error:", err);
    throw new Error(`Failed to read PDF: ${err.message}. Make sure the file is not corrupted or password-protected.`);
  }
}

/**
 * Read Excel using SheetJS (xlsx).
 * Converts all sheets to CSV-like text.
 */
async function readExcel(file) {
  try {
    const XLSX = await import("xlsx");
    const arrayBuffer = await file.arrayBuffer();
    const workbook = XLSX.read(arrayBuffer, { type: "array" });

    const sheets = [];
    for (const sheetName of workbook.SheetNames) {
      const sheet = workbook.Sheets[sheetName];
      const csv = XLSX.utils.sheet_to_csv(sheet);
      if (csv.trim()) {
        sheets.push(`--- Sheet: ${sheetName} ---\n${csv}`);
      }
    }

    const fullText = sheets.join("\n\n");
    return `[Excel: ${file.name} — ${workbook.SheetNames.length} sheet(s)]\n\n${fullText}`;
  } catch (err) {
    console.error("Excel reading error:", err);
    throw new Error(`Failed to read Excel file: ${err.message}`);
  }
}

/**
 * Validate if a file type is supported.
 */
export function isFileSupported(file) {
  const ext = "." + file.name.split(".").pop().toLowerCase();
  return SUPPORTED_FILE_TYPES.includes(ext) || file.type?.startsWith("text/");
}

/**
 * Count words in a text string.
 */
export function wordCount(text) {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

/**
 * Format file size for display.
 */
export function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1048576).toFixed(1)}MB`;
}
