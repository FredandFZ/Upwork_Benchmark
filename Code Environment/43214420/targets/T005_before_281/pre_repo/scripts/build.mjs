import path from "node:path";
import { fileURLToPath } from "node:url";
import { writeDesignArtifacts } from "../src/design.mjs";
import { profile, snapshot } from "../src/snapshot.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
writeDesignArtifacts(path.join(root, "artifacts"), profile, snapshot);
process.stdout.write(`Built deterministic KiCad-compatible board/schematic fixtures for ${snapshot.features.length} requirement states.\n`);
