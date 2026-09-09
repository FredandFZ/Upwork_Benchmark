import path from "node:path";
import { fileURLToPath } from "node:url";
import { profile, snapshot } from "../src/snapshot.mjs";
import { readZip } from "../src/zip.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const entries = readZip(path.join(root, "artifacts", "reconstructed-template.docx"));
process.stdout.write(`${JSON.stringify({ environment: snapshot.environment, feature_count: snapshot.features.length, profile, docx_members: [...entries.keys()].sort() }, null, 2)}\n`);
