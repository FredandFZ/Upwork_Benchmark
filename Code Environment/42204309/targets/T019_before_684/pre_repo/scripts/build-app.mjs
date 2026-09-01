import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import { snapshot } from "../apps/server/src/runtime.mjs";

await rm("dist", { recursive: true, force: true });
await mkdir("dist", { recursive: true });
await cp("apps/web/public", "dist/public", { recursive: true });
await writeFile("dist/build.json", `${JSON.stringify({ featureCount: snapshot.features.length })}\n`);
process.stdout.write(`web build complete (${snapshot.features.length} current features)\n`);
