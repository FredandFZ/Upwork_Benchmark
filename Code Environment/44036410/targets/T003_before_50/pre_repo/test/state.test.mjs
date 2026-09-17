import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { profile, snapshot } from "../src/snapshot.mjs";
import { readZip } from "../src/zip.mjs";
import { dashboard, distributionWarning, explanation, footerForPage, reportCodeLocations, vehiclePresentation } from "../src/operations.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const docxPath = path.join(root, "artifacts", "reconstructed-report.docx");
const pdfPath = path.join(root, "artifacts", "reconstructed-report.pdf");

test("snapshot is internally consistent", () => {
  assert.equal(snapshot.features.length, Object.keys(snapshot.stateMap).length);
  assert.equal(new Set(snapshot.features.map((item) => item.requirement_id)).size, snapshot.features.length);
  for (const feature of snapshot.features) {
    assert.equal(snapshot.stateMap[feature.requirement_id], feature.state_id);
    assert.ok(["ACTIVE", "OBSERVED"].includes(feature.lifecycle));
  }
  assert.equal(profile.activeRequirementCount, snapshot.features.length);
});

test("report operations are behavior-bearing", () => {
  assert.equal(dashboard(profile).fontSize, profile.scoreFontSize);
  assert.equal(explanation(profile).dense, profile.explanationDense);
  assert.equal(vehiclePresentation(profile).completedReportAppearance, !profile.vehicleUsesCheckboxes);
  assert.equal(distributionWarning(profile).prominence, profile.warningStyle);
  assert.equal(footerForPage(profile, 4).present, profile.footerAllPages);
  assert.equal(reportCodeLocations(profile).consistent, new Set([profile.bodyCode, profile.headerCode, profile.footerCode]).size === 1);
});

test("built DOCX is macro-free OOXML with explicit geometry", () => {
  assert.ok(fs.statSync(docxPath).size > 1000);
  const entries = readZip(docxPath);
  for (const name of ["[Content_Types].xml", "_rels/.rels", "docProps/core.xml", "word/document.xml", "word/styles.xml", "word/numbering.xml", "word/settings.xml"]) assert.ok(entries.has(name), `Missing ${name}`);
  assert.equal([...entries.keys()].some((name) => /vbaProject|\.bin$/i.test(name)), false);
  assert.match(entries.get("word/document.xml").toString("utf8"), /w:tblW w:w="9360" w:type="dxa"/);
});

test("built PDF is a deterministic four-page report", () => {
  const pdf = fs.readFileSync(pdfPath);
  const text = pdf.toString("ascii");
  assert.ok(pdf.length > 3000);
  assert.ok(text.startsWith("%PDF-1.4"));
  assert.ok(text.trimEnd().endsWith("%%EOF"));
  assert.equal((text.match(/\/Type \/Page\b/g) ?? []).length, 4);
  assert.ok(text.includes(profile.scoreHeading.toUpperCase()));
  assert.ok(text.includes(`${profile.reportCodeLabel} ${profile.bodyCode}`));
  assert.ok(text.includes(`${profile.footerCode}`) || !profile.footerAllPages);
});
