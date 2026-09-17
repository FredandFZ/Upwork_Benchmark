import fs from "node:fs";
import path from "node:path";

function pdfText(value) {
  return String(value).normalize("NFKD").replace(/[^\x20-\x7E]/g, "?").replaceAll("\\", "\\\\").replaceAll("(", "\\(").replaceAll(")", "\\)");
}

function rgb(hex) {
  const clean = /^[0-9A-F]{6}$/i.test(hex) ? hex : "17365D";
  return [0, 2, 4].map((offset) => (Number.parseInt(clean.slice(offset, offset + 2), 16) / 255).toFixed(3)).join(" ");
}

function text(x, y, size, value, { bold = false, color = "1F2937" } = {}) {
  return `BT /${bold ? "F2" : "F1"} ${size} Tf ${rgb(color)} rg ${x} ${y} Td (${pdfText(value)}) Tj ET\n`;
}

function rect(x, y, width, height, fill, stroke = null) {
  const draw = stroke ? `${rgb(fill)} rg ${rgb(stroke)} RG` : `${rgb(fill)} rg`;
  return `${draw} ${x} ${y} ${width} ${height} re ${stroke ? "B" : "f"}\n`;
}

function line(x1, y1, x2, y2, color = "CBD5E1") {
  return `${rgb(color)} RG 0.8 w ${x1} ${y1} m ${x2} ${y2} l S\n`;
}

function header(profile, page) {
  if (page === 1 || !profile.headerEnabled) return "";
  return text(48, 756, 9, `${profile.reportTitle} | ${profile.headerCode}`, { bold: true, color: profile.accentHex }) + line(48, 744, 564, 744);
}

function footer(profile, page) {
  if (!profile.footerAllPages && page === 4) return "";
  return line(48, 42, 564, 42) + text(48, 26, 8, `Internal | ${profile.footerCode}`, { color: "64748B" }) + text(530, 26, 8, `${page} / 4`, { color: "64748B" });
}

function pageOne(profile) {
  let out = rect(0, 700, 612, 92, profile.accentHex) + text(48, 748, 24, profile.reportTitle, { bold: true, color: "FFFFFF" }) + text(48, 724, 10, `${profile.reportCodeLabel} ${profile.bodyCode} | ${profile.dateLabel}: ${profile.assessmentDate}`, { color: "E2E8F0" });
  out += rect(48, 506, 516, 154, "F1F5F9", "CBD5E1") + text(72, 628, 11, profile.scoreHeading.toUpperCase(), { bold: true, color: profile.accentHex }) + text(72, 570, profile.scoreFontSize, profile.scoreValue, { bold: true, color: profile.dashboardFailed ? "B91C1C" : profile.accentHex }) + text(330, 602, 10, profile.riskHeading.toUpperCase(), { bold: true, color: "64748B" }) + text(330, 570, 22, profile.riskLabel, { bold: true, color: "B45309" });
  out += text(48, 468, 15, profile.dashboardReasonHeading, { bold: true, color: profile.accentHex });
  let y = 442;
  for (const item of profile.explanationItems) { out += text(64, y, profile.explanationDense ? 9 : 10, `- ${item}`, { color: "334155" }); y -= profile.explanationDense ? 18 : 24; }
  out += footer(profile, 1);
  return out;
}

function pageTwo(profile) {
  let out = header(profile, 2) + text(48, 704, 21, profile.detailsHeading, { bold: true, color: profile.accentHex });
  out += text(48, 665, 11, `${profile.subjectLabel}: ${profile.vehicleUsesCheckboxes ? "[ ] Group A   [ ] Group B   [ ] Group C" : profile.subjectValue}`, { color: "334155" });
  out += text(48, 620, 14, profile.contextHeading, { bold: true, color: profile.accentHex });
  let y = 590;
  for (const item of profile.copyLines) { out += text(48, y, 10, item.slice(0, 82), { color: "334155" }); y -= 24; }
  out += text(48, 500, 10, `Body reference: ${profile.bodyCode}`, { color: "64748B" }) + footer(profile, 2);
  return out;
}

function pageThree(profile) {
  let out = header(profile, 3) + text(48, 704, 21, profile.priorityHeading, { bold: true, color: profile.accentHex });
  const rows = [["1", "Immediate", "Address the highest exposure"], ["2", "Near term", "Improve deterrence and control"], ["3", "Ongoing", "Review after material changes"]];
  let y = 640;
  for (const row of rows) { out += rect(48, y - 8, 516, 42, y % 2 === 0 ? "F8FAFC" : "EEF2F7", "CBD5E1") + text(64, y + 7, 10, row[0], { bold: true, color: profile.accentHex }) + text(100, y + 7, 10, row[1], { bold: true }) + text(210, y + 7, 10, row[2]); y -= 54; }
  out += footer(profile, 3);
  return out;
}

function pageFour(profile) {
  let out = header(profile, 4) + text(48, 704, 21, "Closing notes", { bold: true, color: profile.accentHex }) + text(48, 670, 10, "Keep this report with the evaluation record and review the recommendations.");
  if (profile.warningEnabled) {
    const heavy = profile.warningStyle === "heavy";
    out += rect(48, 96, 516, heavy ? 92 : 56, heavy ? "B91C1C" : "FEE2E2", heavy ? null : "FCA5A5") + text(64, heavy ? 150 : 128, 9, profile.warningText.slice(0, 86), { bold: true, color: heavy ? "FFFFFF" : "7F1D1D" });
  }
  out += footer(profile, 4);
  return out;
}

export function pdfBuffer(profile) {
  const objects = [];
  const add = (body) => { objects.push(body); return objects.length; };
  const normalFont = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
  const boldFont = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>");
  const pageIds = [];
  for (const content of [pageOne(profile), pageTwo(profile), pageThree(profile), pageFour(profile)]) {
    const contentId = add(`<< /Length ${Buffer.byteLength(content, "ascii")} >>\nstream\n${content}endstream`);
    const pageId = add(`__PAGE__${contentId}`);
    pageIds.push(pageId);
  }
  const pagesId = add(`<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(" ")}] /Count 4 >>`);
  for (const pageId of pageIds) {
    const contentId = Number(objects[pageId - 1].replace("__PAGE__", ""));
    objects[pageId - 1] = `<< /Type /Page /Parent ${pagesId} 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 ${normalFont} 0 R /F2 ${boldFont} 0 R >> >> /Contents ${contentId} 0 R >>`;
  }
  const catalogId = add(`<< /Type /Catalog /Pages ${pagesId} 0 R >>`);
  let output = "%PDF-1.4\n% deterministic-report\n";
  const offsets = [0];
  objects.forEach((body, index) => { offsets.push(Buffer.byteLength(output, "ascii")); output += `${index + 1} 0 obj\n${body}\nendobj\n`; });
  const xref = Buffer.byteLength(output, "ascii");
  output += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let index = 1; index <= objects.length; index += 1) output += `${String(offsets[index]).padStart(10, "0")} 00000 n \n`;
  output += `trailer\n<< /Size ${objects.length + 1} /Root ${catalogId} 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(output, "ascii");
}

export function writePdf(filePath, profile) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, pdfBuffer(profile));
}
