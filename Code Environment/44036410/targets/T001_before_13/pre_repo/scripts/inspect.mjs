import path from "node:path";
import crypto from "node:crypto";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { profile, snapshot } from "../src/snapshot.mjs";
import { readZip } from "../src/zip.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const entries = readZip(path.join(root, "artifacts", "reconstructed-report.docx"));
const pdf = fs.readFileSync(path.join(root, "artifacts", "reconstructed-report.pdf"));
process.stdout.write(`${JSON.stringify({ environment: snapshot.environment, feature_count: snapshot.features.length, profile, docx_members: [...entries.keys()].sort(), pdf_bytes: pdf.length, pdf_sha256: crypto.createHash("sha256").update(pdf).digest("hex") }, null, 2)}\n`);
