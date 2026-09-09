import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ignored = new Set(["node_modules", "artifacts", ".git", ".render-qa"]);
const files = [];
function visit(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (ignored.has(entry.name)) continue;
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) visit(absolute);
    else if (entry.isFile() && entry.name.endsWith(".mjs")) files.push(absolute);
  }
}
visit(root);
for (const file of files.sort()) {
  const result = spawnSync(process.execPath, ["--check", file], { encoding: "utf8", shell: false });
  if (result.status !== 0) throw new Error(`Syntax check failed: ${file}\n${result.stderr ?? ""}`);
}
if (files.length < 6) throw new Error("Unexpectedly small executable surface");
process.stdout.write(`Syntax checked ${files.length} modules.\n`);
