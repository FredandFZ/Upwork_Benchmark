import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
for (const relative of ["src/snapshot.mjs", "src/profile.mjs", "src/operations.mjs", "src/sexpr.mjs", "src/design.mjs"]) {
  if (!fs.existsSync(path.join(root, relative))) throw new Error(`Missing ${relative}`);
}
process.stdout.write("Static repository contract check passed.\n");
