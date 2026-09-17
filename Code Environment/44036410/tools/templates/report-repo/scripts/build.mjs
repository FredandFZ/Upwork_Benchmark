import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { writeDocument } from "../src/document.mjs";
import { writePdf } from "../src/pdf.mjs";
import { profile, snapshot } from "../src/snapshot.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const artifacts = path.join(root, "artifacts");
fs.mkdirSync(artifacts, { recursive: true });
writeDocument(path.join(artifacts, "reconstructed-report.docx"), profile, snapshot.documentLabel);
writePdf(path.join(artifacts, "reconstructed-report.pdf"), profile);
fs.writeFileSync(path.join(artifacts, "state-summary.json"), `${JSON.stringify({ environment: snapshot.environment, feature_count: snapshot.features.length, state_map: snapshot.stateMap, profile }, null, 2)}\n`, "utf8");
process.stdout.write(`Built deterministic DOCX and four-page PDF for ${snapshot.features.length} requirement states.\n`);
