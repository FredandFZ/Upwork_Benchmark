import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { profile, snapshot } from "../src/snapshot.mjs";
import { readZip } from "../src/zip.mjs";
import { fieldAnchors, resolveBulletProfile, resolveField, resolveTitleStyle } from "../src/operations.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const artifact = path.join(root, "artifacts", "reconstructed-template.docx");

test("snapshot is internally consistent", () => {
  assert.equal(snapshot.features.length, Object.keys(snapshot.stateMap).length);
  assert.equal(new Set(snapshot.features.map((item) => item.requirement_id)).size, snapshot.features.length);
  for (const feature of snapshot.features) {
    assert.equal(snapshot.stateMap[feature.requirement_id], feature.state_id);
    assert.ok(["ACTIVE", "OBSERVED"].includes(feature.lifecycle));
  }
  assert.equal(profile.activeRequirementCount, snapshot.features.length);
});

test("profile has safe explicit Word geometry", () => {
  assert.match(profile.documentLanguage, /^[a-z]{2}-[A-Z]{2}$/);
  assert.ok(profile.titleHalfPoints >= 20 && profile.titleHalfPoints <= 144);
  assert.match(profile.accentHex, /^[0-9A-F]{6}$/);
  assert.equal(profile.formRows.length, 4);
  assert.ok(profile.firstRowIndentDxa >= 0 && profile.firstRowIndentDxa <= 1440);
});

test("document operations expose behavior rather than metadata only", () => {
  assert.equal(resolveTitleStyle(profile).sizePoints, profile.titleHalfPoints / 2);
  assert.equal(resolveBulletProfile(profile).proportionalToText, true);
  assert.equal(fieldAnchors(profile).length, 4);
  assert.deepEqual(resolveField(profile, profile.formRows[1])?.index, 1);
  assert.equal(resolveField(profile, "not-a-field"), null);
});

test("built DOCX is valid, deterministic OOXML", () => {
  assert.ok(fs.statSync(artifact).size > 1000);
  const entries = readZip(artifact);
  const required = ["[Content_Types].xml", "_rels/.rels", "docProps/core.xml", "word/document.xml", "word/styles.xml", "word/numbering.xml", "word/settings.xml"];
  for (const name of required) assert.ok(entries.has(name), `Missing DOCX member ${name}`);
  const documentXml = entries.get("word/document.xml").toString("utf8");
  const stylesXml = entries.get("word/styles.xml").toString("utf8");
  assert.match(documentXml, /w:pgSz w:w="12240" w:h="15840"/);
  assert.match(documentXml, /w:tblW w:w="9360" w:type="dxa"/);
  assert.ok(documentXml.includes(`w:left="${profile.firstRowIndentDxa}"`) || profile.firstRowIndentDxa === 0);
  assert.ok(stylesXml.includes(`w:sz w:val="${profile.titleHalfPoints}"`));
  assert.ok(stylesXml.includes(`w:lang w:val="${profile.documentLanguage}"`));
  for (const bytes of entries.values()) assert.equal(bytes.includes(Buffer.from("<script", "utf8")), false);
});
