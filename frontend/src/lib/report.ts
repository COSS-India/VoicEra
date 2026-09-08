import { jsPDF } from "jspdf";

export interface ReportMeta {
  orgName: string;
  email: string;
}

export function csvCell(v: unknown): string {
  return `"${String(v ?? "").replace(/"/g, '""')}"`;
}

function metaRow(label: string, value: string): string {
  return [label, value].map(csvCell).join(",");
}

/** Every exported CSV in the app opens with the same organisation/downloaded-by/
 * generated-at header before the real column header row, so a report can
 * always be traced back to who pulled it and from where. */
export function buildCsvReport(meta: ReportMeta, header: string[], rows: unknown[][]): string {
  const lines = [
    metaRow("Organisation", meta.orgName),
    metaRow("Downloaded by", meta.email),
    metaRow("Generated", new Date().toLocaleString()),
    "",
    header.map(csvCell).join(","),
    ...rows.map((r) => r.map(csvCell).join(",")),
  ];
  return lines.join("\n");
}

export function downloadBlob(content: BlobPart, type: string, filename: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const PDF_MARGIN_X = 14;
const PDF_PAGE_RIGHT = 196;
const PDF_PAGE_BOTTOM = 280;

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "");
  const full = clean.length === 3
    ? clean.split("").map((c) => c + c).join("")
    : clean.padEnd(6, "0");
  const value = parseInt(full, 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

/** Every exported PDF in the app opens with the same title + organisation +
 * "downloaded by" + generated-at header, so a printed report is always
 * traceable back to who pulled it and from where. Returns small helpers that
 * track the vertical cursor and page-break for the caller's own sections. */
export function createPdfReport(title: string, meta: ReportMeta) {
  const doc = new jsPDF();
  let y = 20;

  function ensureRoom(next: number) {
    if (y + next > PDF_PAGE_BOTTOM) {
      doc.addPage();
      y = 20;
    }
  }

  doc.setFontSize(18);
  doc.setFont("helvetica", "bold");
  doc.text(title, PDF_MARGIN_X, y);
  y += 8;

  doc.setFontSize(10);
  doc.setFont("helvetica", "normal");
  doc.setTextColor(120);
  doc.text(meta.orgName, PDF_MARGIN_X, y);
  y += 5;
  doc.text(`Downloaded by ${meta.email}`, PDF_MARGIN_X, y);
  y += 5;
  doc.text(`Generated ${new Date().toLocaleString()}`, PDF_MARGIN_X, y);
  doc.setTextColor(0);
  y += 6;
  doc.setDrawColor(210);
  doc.line(PDF_MARGIN_X, y, PDF_PAGE_RIGHT, y);
  y += 10;

  function heading(text: string) {
    ensureRoom(12);
    doc.setFontSize(13);
    doc.setFont("helvetica", "bold");
    doc.text(text, PDF_MARGIN_X, y);
    y += 8;
    doc.setFontSize(11);
    doc.setFont("helvetica", "normal");
  }

  function row(label: string, value: string) {
    ensureRoom(6);
    doc.text(label, PDF_MARGIN_X, y);
    doc.text(value, PDF_MARGIN_X + 90, y);
    y += 6;
  }

  function paragraph(text: string) {
    ensureRoom(6);
    doc.text(text, PDF_MARGIN_X, y);
    y += 6;
  }

  const BAR_LABEL_MAX_WIDTH = 60;
  const BAR_X = PDF_MARGIN_X + BAR_LABEL_MAX_WIDTH + 3;
  const BAR_MAX_WIDTH = 90;
  const BAR_HEIGHT = 4;

  /** One horizontal bar-chart row: a label, a colored bar sized by `fraction`
   * (0-1) of the series' max value, and a value label after it — the actual
   * "graph" behind Overview/Agent Performance/Model Usage/Connection
   * Breakdown, drawn as real vector shapes (no image rasterization, so it
   * stays crisp and never fights CSS custom properties or embedded HTML). */
  function barRow(label: string, valueLabel: string, fraction: number, color: string) {
    ensureRoom(7);
    doc.setFontSize(9);
    doc.setTextColor(50);
    doc.text(label, PDF_MARGIN_X, y, { maxWidth: BAR_LABEL_MAX_WIDTH });

    doc.setFillColor(230, 230, 230);
    doc.rect(BAR_X, y - 3.2, BAR_MAX_WIDTH, BAR_HEIGHT, "F");
    const width = Math.max(0.6, Math.min(1, fraction) * BAR_MAX_WIDTH);
    doc.setFillColor(...hexToRgb(color));
    doc.rect(BAR_X, y - 3.2, width, BAR_HEIGHT, "F");

    if (valueLabel) {
      doc.setTextColor(50);
      doc.text(valueLabel, BAR_X + BAR_MAX_WIDTH + 3, y);
    }
    doc.setTextColor(0);
    doc.setFontSize(11);
    y += 7;
  }

  return {
    doc,
    heading,
    row,
    paragraph,
    barRow,
    ensureRoom,
    save(filename: string) {
      doc.save(filename);
    },
  };
}
