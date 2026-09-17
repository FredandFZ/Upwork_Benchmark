import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { profile, snapshot } from "../src/snapshot.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const hashes = Object.fromEntries(["design.kicad_pcb", "design.kicad_sch", "design-state.json"].map((name) => [name, crypto.createHash("sha256").update(fs.readFileSync(path.join(root, "artifacts", name))).digest("hex")]));
process.stdout.write(`${JSON.stringify({ environment: snapshot.environment, feature_count: snapshot.features.length, profile, artifact_sha256: hashes }, null, 2)}\n`);
