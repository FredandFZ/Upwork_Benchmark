import fs from "node:fs";
import path from "node:path";
import { snapshot } from "../apps/site/src/runtime.mjs";

const root = process.cwd();
const output = path.join(root, "dist");
fs.rmSync(output, { recursive: true, force: true });
fs.mkdirSync(output, { recursive: true });
fs.cpSync(path.join(root, "apps", "site", "public"), path.join(output, "web"), { recursive: true });
fs.writeFileSync(path.join(output, "runtime.json"), JSON.stringify(snapshot, null, 2) + "\n", "utf8");
process.stdout.write("Built " + snapshot.features.length + " capabilities into dist/.\n");
