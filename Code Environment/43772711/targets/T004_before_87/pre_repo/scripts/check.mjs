import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const ignored = new Set(["node_modules", "dist", ".git"]);
const files = [];
function visit(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (ignored.has(entry.name)) continue;
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) visit(absolute);
    else if (entry.isFile() && new Set([".js", ".mjs"]).has(path.extname(entry.name))) files.push(absolute);
  }
}
visit(process.cwd());
for (const file of files.sort()) {
  const result = spawnSync(process.execPath, ["--check", file], { encoding: "utf8" });
  if (result.status !== 0) {
    process.stderr.write(result.stderr || result.stdout);
    process.exit(result.status ?? 1);
  }
}
process.stdout.write("Syntax checked " + files.length + " JavaScript files.\n");
