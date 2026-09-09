#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";

const PROJECT_ID = "44035087";
const SCHEMA_VERSION = "2.0";
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = path.resolve(SCRIPT_DIR, "..");
const WORKSPACE_ROOT = path.resolve(PACKAGE_ROOT, "..", "..");

const INPUTS = Object.freeze({
  requirementGraph: path.join(WORKSPACE_ROOT, "outputs", "stage2", PROJECT_ID, "requirement_state_graph.json"),
  goldStates: path.join(WORKSPACE_ROOT, "outputs", "stage2", PROJECT_ID, "gold_states.json"),
  normalizedProject: path.join(WORKSPACE_ROOT, "outputs", "stage1_runs", PROJECT_ID, "normalized_project.json"),
  stage1Annotation: path.join(WORKSPACE_ROOT, "outputs", "stage1_annotations", `${PROJECT_ID}_stage1_annotation.json`),
  chatMessages: path.join(WORKSPACE_ROOT, "Datasets", "project", PROJECT_ID, "chat_messages.json"),
  jobDescription: path.join(WORKSPACE_ROOT, "Datasets", "project", PROJECT_ID, "job.txt"),
});

const OUTPUTS = Object.freeze({
  cenv: path.join(PACKAGE_ROOT, "C_env"),
  reports: path.join(PACKAGE_ROOT, "reports"),
  targets: path.join(PACKAGE_ROOT, "targets"),
});

const EXCLUDED_TREE_PARTS = new Set(["node_modules", "out", "cache", "dist", ".git", "__pycache__"]);
const NON_CODE_REQUIREMENT_IDS = new Set();
const FIXED_DOS_TIME = 0;
const FIXED_DOS_DATE = 33;

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function jsonText(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function writeText(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content, "utf8");
}

function writeJson(filePath, value) {
  writeText(filePath, jsonText(value));
}

function sha256Buffer(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function sha256File(filePath) {
  return sha256Buffer(fs.readFileSync(filePath));
}

function toPosix(relativePath) {
  return relativePath.split(path.sep).join("/");
}

function safeResetDirectory(directoryPath) {
  const resolved = path.resolve(directoryPath);
  const parent = path.dirname(resolved);
  invariant(parent === PACKAGE_ROOT, `Refusing to reset a directory outside ${PACKAGE_ROOT}: ${resolved}`);
  invariant(new Set(Object.values(OUTPUTS).map((item) => path.resolve(item))).has(resolved), `Unexpected reset target: ${resolved}`);
  fs.rmSync(resolved, { recursive: true, force: true });
  fs.mkdirSync(resolved, { recursive: true });
}

function listFiles(root, { applyTreeExclusions = false } = {}) {
  const files = [];

  function visit(current) {
    const entries = fs.readdirSync(current, { withFileTypes: true }).sort((left, right) => left.name.localeCompare(right.name, "en"));
    for (const entry of entries) {
      const absolute = path.join(current, entry.name);
      const relative = path.relative(root, absolute);
      const parts = relative.split(path.sep);
      if (applyTreeExclusions && parts.some((part) => EXCLUDED_TREE_PARTS.has(part))) continue;
      invariant(!entry.isSymbolicLink(), `Symbolic links are not permitted in reconstructed repositories: ${absolute}`);
      if (entry.isDirectory()) visit(absolute);
      else if (entry.isFile()) files.push({ absolute, relative: toPosix(relative) });
      else throw new Error(`Unsupported filesystem entry: ${absolute}`);
    }
  }

  visit(root);
  return files.sort((left, right) => left.relative.localeCompare(right.relative, "en"));
}

function sha256Tree(root) {
  const hash = crypto.createHash("sha256");
  for (const file of listFiles(root, { applyTreeExclusions: true })) {
    hash.update(Buffer.from(file.relative, "utf8"));
    hash.update(Buffer.from([0]));
    hash.update(fs.readFileSync(file.absolute));
    hash.update(Buffer.from([0]));
  }
  return hash.digest("hex");
}

function slugify(value) {
  const slug = value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-");
  invariant(slug.length > 0, `Unable to derive a safe slug from: ${value}`);
  return slug;
}

function identifierFromSlug(slug) {
  return `feature${slug.split("-").map((part) => `${part[0].toUpperCase()}${part.slice(1)}`).join("")}`;
}

function stateMapFromGold(goldState) {
  return new Map(goldState.requirement_states.map((item) => [item.requirement_id, item.state_id]));
}

function stateMapAsObject(stateMap) {
  return Object.fromEntries([...stateMap.entries()].sort(([left], [right]) => left.localeCompare(right, "en")));
}

function assertSameStateMap(actual, expected, context) {
  const actualObject = stateMapAsObject(actual);
  const expectedObject = stateMapAsObject(expected);
  invariant(
    JSON.stringify(actualObject) === JSON.stringify(expectedObject),
    `${context} state mismatch.\nExpected: ${JSON.stringify(expectedObject)}\nActual: ${JSON.stringify(actualObject)}`,
  );
}

function copyStateMap(stateMap) {
  return new Map(stateMap.entries());
}

function crc32Table() {
  const table = new Uint32Array(256);
  for (let index = 0; index < 256; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : (value >>> 1);
    table[index] = value >>> 0;
  }
  return table;
}

const CRC32_TABLE = crc32Table();

function crc32(buffer) {
  let value = 0xffffffff;
  for (const byte of buffer) value = CRC32_TABLE[(value ^ byte) & 0xff] ^ (value >>> 8);
  return (value ^ 0xffffffff) >>> 0;
}

function zipPathIsSafe(entryName) {
  if (!entryName || entryName.includes("\\") || entryName.startsWith("/") || /^[A-Za-z]:/.test(entryName)) return false;
  const parts = entryName.split("/");
  return !parts.some((part) => part === ".." || part.toLowerCase() === ".git");
}

function createDeterministicZip(sourceRoot, archivePath, rootPrefix = "") {
  const files = listFiles(sourceRoot, { applyTreeExclusions: true });
  const localRecords = [];
  const centralRecords = [];
  let offset = 0;

  for (const file of files) {
    const entryName = rootPrefix ? `${rootPrefix.replace(/\/$/, "")}/${file.relative}` : file.relative;
    invariant(zipPathIsSafe(entryName), `Unsafe archive entry path: ${entryName}`);
    const name = Buffer.from(entryName, "utf8");
    const raw = fs.readFileSync(file.absolute);
    const compressed = zlib.deflateRawSync(raw, { level: 9 });
    const checksum = crc32(raw);

    const localHeader = Buffer.alloc(30);
    localHeader.writeUInt32LE(0x04034b50, 0);
    localHeader.writeUInt16LE(20, 4);
    localHeader.writeUInt16LE(0x0800, 6);
    localHeader.writeUInt16LE(8, 8);
    localHeader.writeUInt16LE(FIXED_DOS_TIME, 10);
    localHeader.writeUInt16LE(FIXED_DOS_DATE, 12);
    localHeader.writeUInt32LE(checksum, 14);
    localHeader.writeUInt32LE(compressed.length, 18);
    localHeader.writeUInt32LE(raw.length, 22);
    localHeader.writeUInt16LE(name.length, 26);
    localHeader.writeUInt16LE(0, 28);
    localRecords.push(localHeader, name, compressed);

    const centralHeader = Buffer.alloc(46);
    centralHeader.writeUInt32LE(0x02014b50, 0);
    centralHeader.writeUInt16LE((3 << 8) | 20, 4);
    centralHeader.writeUInt16LE(20, 6);
    centralHeader.writeUInt16LE(0x0800, 8);
    centralHeader.writeUInt16LE(8, 10);
    centralHeader.writeUInt16LE(FIXED_DOS_TIME, 12);
    centralHeader.writeUInt16LE(FIXED_DOS_DATE, 14);
    centralHeader.writeUInt32LE(checksum, 16);
    centralHeader.writeUInt32LE(compressed.length, 20);
    centralHeader.writeUInt32LE(raw.length, 24);
    centralHeader.writeUInt16LE(name.length, 28);
    centralHeader.writeUInt16LE(0, 30);
    centralHeader.writeUInt16LE(0, 32);
    centralHeader.writeUInt16LE(0, 34);
    centralHeader.writeUInt16LE(0, 36);
    centralHeader.writeUInt32LE((0o100644 << 16) >>> 0, 38);
    centralHeader.writeUInt32LE(offset, 42);
    centralRecords.push(centralHeader, name);
    offset += localHeader.length + name.length + compressed.length;
  }

  invariant(files.length > 0, `Refusing to create an empty archive: ${archivePath}`);
  const centralDirectory = Buffer.concat(centralRecords);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(centralDirectory.length, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);
  fs.mkdirSync(path.dirname(archivePath), { recursive: true });
  fs.writeFileSync(archivePath, Buffer.concat([...localRecords, centralDirectory, end]));
}

function validateZip(archivePath) {
  const archive = fs.readFileSync(archivePath);
  let eocdOffset = -1;
  for (let offset = archive.length - 22; offset >= Math.max(0, archive.length - 65557); offset -= 1) {
    if (archive.readUInt32LE(offset) === 0x06054b50) {
      eocdOffset = offset;
      break;
    }
  }
  invariant(eocdOffset >= 0, `ZIP end-of-central-directory record not found: ${archivePath}`);
  const entryCount = archive.readUInt16LE(eocdOffset + 10);
  const centralOffset = archive.readUInt32LE(eocdOffset + 16);
  let cursor = centralOffset;
  let totalUncompressedBytes = 0;
  const names = [];

  for (let index = 0; index < entryCount; index += 1) {
    invariant(archive.readUInt32LE(cursor) === 0x02014b50, `Invalid central directory entry ${index} in ${archivePath}`);
    const flags = archive.readUInt16LE(cursor + 8);
    const method = archive.readUInt16LE(cursor + 10);
    const expectedCrc = archive.readUInt32LE(cursor + 16);
    const compressedSize = archive.readUInt32LE(cursor + 20);
    const uncompressedSize = archive.readUInt32LE(cursor + 24);
    const nameLength = archive.readUInt16LE(cursor + 28);
    const extraLength = archive.readUInt16LE(cursor + 30);
    const commentLength = archive.readUInt16LE(cursor + 32);
    const externalAttributes = archive.readUInt32LE(cursor + 38);
    const localOffset = archive.readUInt32LE(cursor + 42);
    const entryName = archive.subarray(cursor + 46, cursor + 46 + nameLength).toString((flags & 0x0800) ? "utf8" : "latin1");
    invariant(zipPathIsSafe(entryName), `Unsafe entry in ${archivePath}: ${entryName}`);
    const unixMode = (externalAttributes >>> 16) & 0xffff;
    invariant((unixMode & 0o170000) !== 0o120000, `Symlink entry is forbidden: ${entryName}`);
    invariant(archive.readUInt32LE(localOffset) === 0x04034b50, `Missing local header for ${entryName}`);
    const localNameLength = archive.readUInt16LE(localOffset + 26);
    const localExtraLength = archive.readUInt16LE(localOffset + 28);
    const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = archive.subarray(dataOffset, dataOffset + compressedSize);
    let raw;
    if (method === 8) raw = zlib.inflateRawSync(compressed);
    else if (method === 0) raw = compressed;
    else throw new Error(`Unsupported ZIP method ${method} for ${entryName}`);
    invariant(raw.length === uncompressedSize, `Uncompressed size mismatch for ${entryName}`);
    invariant(crc32(raw) === expectedCrc, `CRC mismatch for ${entryName}`);
    totalUncompressedBytes += raw.length;
    names.push(entryName);
    cursor += 46 + nameLength + extraLength + commentLength;
  }

  invariant(names.length === entryCount && entryCount > 0, `Invalid ZIP entry count: ${archivePath}`);
  return {
    status: "PASS",
    archive_sha256: sha256Buffer(archive),
    archive_bytes: archive.length,
    entry_count: entryCount,
    uncompressed_bytes: totalUncompressedBytes,
    safe_paths: true,
    crc_verified: true,
    symlink_free: true,
    git_metadata_free: true,
  };
}

function featureDescriptor(requirementGraph, stateNode) {
  const ambiguities = Object.values(stateNode.ambiguity ?? {}).map((item) => ({
    status: item.status,
    dimension: item.dimension,
    description: item.description,
  }));
  const execution = stateNode.execution ? {
    status: stateNode.execution.status,
    observed_behavior: stateNode.execution.observed_behavior,
  } : null;
  return {
    key: slugify(requirementGraph.title),
    title: requirementGraph.title,
    family: requirementGraph.family_id,
    lifecycle: lifecycleOf(stateNode),
    components: stateNode.scope?.components ?? [],
    contexts: stateNode.scope?.contexts ?? [],
    configuration: stateNode.attributes ?? {},
    ambiguities,
    execution,
  };
}

function lifecycleOf(stateNode) {
  return stateNode.lifecycle_status ?? "OBSERVED";
}

function isCodeProjected(requirementGraph, stateNode) {
  return !NON_CODE_REQUIREMENT_IDS.has(requirementGraph.requirement_id)
    && !new Set(["REMOVED", "DEFERRED"]).has(lifecycleOf(stateNode));
}

function projectFiles({ features, environmentLabel }) {
  const featureImports = features.map(({ descriptor }) => {
    const slug = descriptor.key;
    return `import ${identifierFromSlug(slug)} from "./features/${slug}.mjs";`;
  }).join("\n");
  const featureIdentifiers = features.map(({ descriptor }) => identifierFromSlug(descriptor.key)).join(", ");

  const runtimeSource = `${featureImports}${featureImports ? "\n\n" : ""}const features = Object.freeze([${featureIdentifiers}]);

export const snapshot = Object.freeze({
  environment: ${JSON.stringify(environmentLabel)},
  product: "Website workspace",
  features,
});

export function featuresForViewport(viewport) {
  if (!new Set(["desktop", "tablet", "mobile"]).has(viewport)) return [];
  return features;
}

export function diagnostics() {
  return features
    .filter((feature) => feature.execution)
    .map((feature) => ({ key: feature.key, ...feature.execution }));
}

export function openQuestions() {
  return features.flatMap((feature) => feature.ambiguities.map((ambiguity) => ({ key: feature.key, ...ambiguity })));
}
`;

  const serverSource = `import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { diagnostics, featuresForViewport, openQuestions, snapshot } from "../site/src/runtime.mjs";

const publicRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "site", "public");
const contentTypes = new Map([[".html", "text/html; charset=utf-8"], [".js", "text/javascript; charset=utf-8"], [".css", "text/css; charset=utf-8"]]);

function sendJson(response, status, value) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  response.end(JSON.stringify(value));
}

export function createServer() {
  return http.createServer((request, response) => {
    const requestUrl = new URL(request.url ?? "/", "http://localhost");
    if (request.method === "GET" && requestUrl.pathname === "/health") return sendJson(response, 200, { status: "ok" });
    if (request.method === "GET" && requestUrl.pathname === "/api/snapshot") return sendJson(response, 200, snapshot);
    if (request.method === "GET" && requestUrl.pathname === "/api/diagnostics") return sendJson(response, 200, { diagnostics: diagnostics() });
    if (request.method === "GET" && requestUrl.pathname === "/api/open-questions") return sendJson(response, 200, { questions: openQuestions() });
    if (request.method === "GET" && requestUrl.pathname.startsWith("/api/viewport/")) {
      const viewport = requestUrl.pathname.slice("/api/viewport/".length);
      if (!new Set(["desktop", "tablet", "mobile"]).has(viewport)) return sendJson(response, 404, { error: "unknown viewport" });
      return sendJson(response, 200, { viewport, features: featuresForViewport(viewport) });
    }
    if (request.method !== "GET" && request.method !== "HEAD") return sendJson(response, 405, { error: "method not allowed" });
    const relative = requestUrl.pathname === "/" ? "index.html" : requestUrl.pathname.replace(/^\\/+/, "");
    const candidate = path.resolve(publicRoot, relative);
    if (!candidate.startsWith(publicRoot + path.sep) || !fs.existsSync(candidate) || !fs.statSync(candidate).isFile()) return sendJson(response, 404, { error: "not found" });
    response.writeHead(200, { "content-type": contentTypes.get(path.extname(candidate)) ?? "application/octet-stream" });
    if (request.method === "HEAD") return response.end();
    fs.createReadStream(candidate).pipe(response);
  });
}

export function startServer({ host = process.env.HOST ?? "127.0.0.1", port = Number(process.env.PORT ?? 4403) } = {}) {
  const server = createServer();
  server.listen(port, host, () => process.stdout.write("Website workspace listening on http://" + host + ":" + port + "\\n"));
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) startServer();
`;

  const browserSource = `const statusNode = document.querySelector("[data-status]");
const featureNode = document.querySelector("[data-features]");

function renderFeature(feature) {
  const article = document.createElement("article");
  article.className = "card";
  const title = document.createElement("h2");
  title.textContent = feature.title;
  const family = document.createElement("p");
  family.className = "eyebrow";
  family.textContent = [feature.family, feature.lifecycle, feature.execution?.status].filter(Boolean).join(" · ");
  const configuration = document.createElement("pre");
  configuration.textContent = JSON.stringify(feature.configuration, null, 2);
  article.append(title, family, configuration);
  return article;
}

async function boot() {
  const response = await fetch("/api/snapshot");
  if (!response.ok) throw new Error("Snapshot request failed with " + response.status);
  const snapshot = await response.json();
  statusNode.textContent = String(snapshot.features.length) + " reconstructed capabilities";
  if (snapshot.features.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "This baseline is ready for the first project change.";
    featureNode.append(empty);
    return;
  }
  for (const feature of snapshot.features) featureNode.append(renderFeature(feature));
}

boot().catch((error) => {
  statusNode.textContent = "Runtime unavailable";
  statusNode.dataset.error = error.message;
});
`;

  const htmlSource = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Website Workspace</title>
    <link rel="stylesheet" href="/styles.css">
  </head>
  <body>
    <main>
      <p class="eyebrow">Executable reconstruction</p>
      <h1>Website Workspace</h1>
      <p data-status>Loading runtime snapshot...</p>
      <section class="grid" data-features aria-live="polite"></section>
    </main>
    <script type="module" src="/app.js"></script>
  </body>
</html>
`;

  const cssSource = `:root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #08111f; color: #e7eefb; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: radial-gradient(circle at 20% 0%, #163156, transparent 42%), #08111f; }
main { width: min(1100px, calc(100% - 2rem)); margin: 0 auto; padding: 4rem 0; }
h1 { margin: .2rem 0 .6rem; font-size: clamp(2.4rem, 7vw, 5.2rem); letter-spacing: -.055em; }
.eyebrow { color: #7dd3fc; font-size: .78rem; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; margin-top: 2rem; }
.card { min-width: 0; padding: 1.2rem; border: 1px solid #29466d; border-radius: 18px; background: rgba(13, 28, 49, .86); box-shadow: 0 18px 55px rgba(0, 0, 0, .24); }
.card h2 { margin: .25rem 0 .8rem; font-size: 1.15rem; }
pre { max-height: 18rem; overflow: auto; padding: .85rem; border-radius: 10px; background: #050b14; color: #bfdbfe; font-size: .75rem; white-space: pre-wrap; word-break: break-word; }
.empty { padding: 2rem; border: 1px dashed #34547d; border-radius: 18px; color: #b7c7dd; }
`;

  const buildSource = `import fs from "node:fs";
import path from "node:path";
import { snapshot } from "../apps/site/src/runtime.mjs";

const root = process.cwd();
const output = path.join(root, "dist");
fs.rmSync(output, { recursive: true, force: true });
fs.mkdirSync(output, { recursive: true });
fs.cpSync(path.join(root, "apps", "site", "public"), path.join(output, "web"), { recursive: true });
fs.writeFileSync(path.join(output, "runtime.json"), JSON.stringify(snapshot, null, 2) + "\\n", "utf8");
process.stdout.write("Built " + snapshot.features.length + " capabilities into dist/.\\n");
`;

  const checkSource = `import { spawnSync } from "node:child_process";
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
process.stdout.write("Syntax checked " + files.length + " JavaScript files.\\n");
`;

  const testSource = `import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer } from "../apps/server/server.mjs";
import { diagnostics, featuresForViewport, openQuestions, snapshot } from "../apps/site/src/runtime.mjs";

let server;
let origin;

before(async () => {
  server = createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  origin = "http://127.0.0.1:" + server.address().port;
});

after(async () => {
  if (server) await new Promise((resolve) => server.close(resolve));
});

test("runtime has unique, valid capability keys", () => {
  const keys = snapshot.features.map((feature) => feature.key);
  assert.equal(new Set(keys).size, keys.length);
  assert.ok(snapshot.features.every((feature) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(feature.key)));
});

test("viewport projections only contain known capabilities", () => {
  const known = new Set(snapshot.features);
  for (const viewport of ["desktop", "tablet", "mobile"]) assert.ok(featuresForViewport(viewport).every((feature) => known.has(feature)));
  assert.deepEqual(featuresForViewport("unknown"), []);
});

test("diagnostics and open questions are projected from the reconstructed state", () => {
  assert.deepEqual(diagnostics().map((item) => item.key), snapshot.features.filter((feature) => feature.execution).map((feature) => feature.key));
  assert.equal(openQuestions().length, snapshot.features.reduce((count, feature) => count + feature.ambiguities.length, 0));
});

test("health and snapshot endpoints are runnable", async () => {
  const health = await fetch(origin + "/health");
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { status: "ok" });
  const response = await fetch(origin + "/api/snapshot");
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.features.length, snapshot.features.length);
  const diagnosticResponse = await fetch(origin + "/api/diagnostics");
  assert.equal(diagnosticResponse.status, 200);
  assert.deepEqual((await diagnosticResponse.json()).diagnostics, diagnostics());
});

test("static shell is served", async () => {
  const response = await fetch(origin);
  assert.equal(response.status, 200);
  assert.match(await response.text(), /Website Workspace/);
});
`;

  return {
    "apps/site/src/runtime.mjs": runtimeSource,
    "apps/site/public/app.js": browserSource,
    "apps/site/public/index.html": htmlSource,
    "apps/site/public/styles.css": cssSource,
    "apps/server/server.mjs": serverSource,
    "scripts/build.mjs": buildSource,
    "scripts/check.mjs": checkSource,
    "test/runtime.test.mjs": testSource,
  };
}

function createRunnableRepository(destination, { features, environmentLabel, repositoryLabel }) {
  fs.mkdirSync(destination, { recursive: true });
  const packageJson = {
    name: "reconstructed-website-workspace",
    version: "1.0.0",
    private: true,
    type: "module",
    description: "Offline-runnable executable reconstruction of a responsive website workspace.",
    engines: { node: ">=20" },
    scripts: {
      start: "node apps/server/server.mjs",
      build: "node scripts/build.mjs",
      test: "node --test --test-reporter=tap",
      check: "node scripts/check.mjs && npm run build && npm test",
    },
  };
  const packageLock = {
    name: packageJson.name,
    version: packageJson.version,
    lockfileVersion: 3,
    requires: true,
    packages: {
      "": {
        name: packageJson.name,
        version: packageJson.version,
        engines: packageJson.engines,
      },
    },
  };

  const staticFiles = {
    ".dockerignore": "node_modules\ndist\n.git\n*.zip\n",
    ".env.example": "HOST=127.0.0.1\nPORT=4403\n",
    ".gitignore": "node_modules/\ndist/\n.env\n",
    "Dockerfile": "FROM node:22-alpine\nWORKDIR /app\nCOPY package.json package-lock.json ./\nRUN npm ci --omit=dev\nCOPY . .\nRUN npm run build\nEXPOSE 4403\nCMD [\"npm\", \"start\"]\n",
    "Makefile": ".PHONY: install check build test start clean\n\ninstall:\n\tnpm ci\n\ncheck:\n\tnpm run check\n\nbuild:\n\tnpm run build\n\ntest:\n\tnpm test\n\nstart:\n\tnpm start\n\nclean:\n\trm -rf dist node_modules\n",
    "README.md": `# ${repositoryLabel}\n\nThis repository is an executable reconstruction, not a copy of the unavailable historical WordPress/Elementor source tree. It preserves the observable responsive-site capability state in a deterministic, dependency-free Node.js harness.\n\n## Run\n\n\`\`\`sh\nnpm ci\nnpm run check\nnpm start\n\`\`\`\n\nOpen http://127.0.0.1:4403. The JSON interfaces are available at \`/health\`, \`/api/snapshot\`, \`/api/diagnostics\`, \`/api/open-questions\`, and \`/api/viewport/{desktop|tablet|mobile}\`.\n\nNode.js 20 or newer is required. No network service or credential is needed.\n`,
    "docker-compose.yml": "services:\n  workspace:\n    build: .\n    ports:\n      - \"4403:4403\"\n    environment:\n      HOST: 0.0.0.0\n      PORT: 4403\n",
    "package.json": jsonText(packageJson),
    "package-lock.json": jsonText(packageLock),
    ...projectFiles({ features, environmentLabel }),
  };

  for (const [relativePath, content] of Object.entries(staticFiles)) writeText(path.join(destination, relativePath), content);
  for (const { descriptor } of features) {
    writeText(path.join(destination, "apps", "site", "src", "features", `${descriptor.key}.mjs`), `export default Object.freeze(${JSON.stringify(descriptor, null, 2)});\n`);
  }
}

function runCommand(cwd, executable, args) {
  const command = [executable, ...args].join(" ");
  const invokedExecutable = process.platform === "win32" ? (process.env.ComSpec ?? "cmd.exe") : executable;
  const invokedArgs = process.platform === "win32" ? ["/d", "/s", "/c", command] : args;
  const result = spawnSync(invokedExecutable, invokedArgs, {
    cwd,
    encoding: "utf8",
    env: { ...process.env, NO_COLOR: "1", npm_config_audit: "false", npm_config_fund: "false", npm_config_update_notifier: "false" },
    shell: false,
  });
  const stdout = (result.stdout ?? "").trim();
  const stderr = (result.stderr ?? "").trim();
  invariant(result.status === 0, `Command failed in ${cwd}: ${command}\n${stdout}\n${stderr}`);
  return { command, status: "PASS", exit_code: result.status };
}

function validateRunnableRepository(repositoryPath) {
  const npmExecutable = process.platform === "win32" ? "npm.cmd" : "npm";
  const commands = [
    runCommand(repositoryPath, npmExecutable, ["ci", "--ignore-scripts"]),
    runCommand(repositoryPath, npmExecutable, ["run", "check"]),
  ];
  for (const ignored of ["node_modules", "dist", "out", "cache"]) fs.rmSync(path.join(repositoryPath, ignored), { recursive: true, force: true });
  return { status: "PASS", commands };
}

function scanTextFiles(root, patterns) {
  const findings = [];
  for (const file of listFiles(root, { applyTreeExclusions: true })) {
    const buffer = fs.readFileSync(file.absolute);
    if (buffer.includes(0)) continue;
    const text = buffer.toString("utf8");
    for (const pattern of patterns) {
      pattern.regex.lastIndex = 0;
      if (pattern.regex.test(text)) findings.push({ path: file.relative, rule: pattern.name });
    }
  }
  return findings;
}

const SECRET_PATTERNS = Object.freeze([
  { name: "private-key", regex: /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/i },
  { name: "aws-access-key", regex: /AKIA[0-9A-Z]{16}/ },
  { name: "github-token", regex: /gh[pousr]_[A-Za-z0-9]{30,}/ },
  { name: "slack-token", regex: /xox[baprs]-[A-Za-z0-9-]{20,}/ },
  { name: "openai-key", regex: /sk-[A-Za-z0-9_-]{32,}/ },
  { name: "email-address", regex: /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i },
  { name: "credential-assignment", regex: /(?:password|passwd|pwd)\s*[:=]\s*(?!placeholder|example|not-set)[^\s]{6,}/i },
  { name: "external-production-url", regex: /https?:\/\/[A-Za-z0-9.-]+\.(?:com|net|org|io|ai|co|dev|app)\b/i },
  { name: "account-assignment", regex: /\b(?:username|account(?:_name)?)\s*[:=]\s*(?!placeholder|example)[A-Za-z0-9_.@-]{3,}/i },
  { name: "redacted-sensitive-token", regex: /\[(?:PASSWORD|ACCOUNT|EMAIL)_\d+\]/i },
]);

const CENV_FORBIDDEN_PATTERNS = Object.freeze([
  "instant quote", "gallery", "homepage", "hero presentation", "pricing", "portfolio", "hover animation",
  "service-specific", "calendly", "book a session", "quote form", "square-footage", "client-supplied", "video", "image-focused",
].map((term) => ({ name: `future-domain-term:${term}`, regex: new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i") })));

function sourceChecksums() {
  return Object.fromEntries(Object.entries(INPUTS).map(([name, filePath]) => {
    invariant(fs.existsSync(filePath), `Required source artifact is missing: ${filePath}`);
    return [name, {
      path: toPosix(path.relative(WORKSPACE_ROOT, filePath)),
      sha256: sha256File(filePath),
      bytes: fs.statSync(filePath).size,
    }];
  }));
}

function buildIndexes(requirementData, normalizedProject) {
  const messageOrder = new Map(normalizedProject.messages.map((message, index) => [message.message_id, index]));
  const graphByRequirement = new Map();
  const stateById = new Map();
  const eventById = new Map();
  const events = [];

  requirementData.requirement_graphs.forEach((requirementGraph, graphIndex) => {
    invariant(!graphByRequirement.has(requirementGraph.requirement_id), `Duplicate requirement graph: ${requirementGraph.requirement_id}`);
    graphByRequirement.set(requirementGraph.requirement_id, requirementGraph);
    for (const stateNode of requirementGraph.nodes) {
      invariant(!stateById.has(stateNode.state_id), `Duplicate state node: ${stateNode.state_id}`);
      stateById.set(stateNode.state_id, { requirementGraph, stateNode });
    }
    requirementGraph.edges.forEach((edge, edgeIndex) => {
      invariant(messageOrder.has(edge.source_message_id), `Event ${edge.event_id} points to an unknown message ${edge.source_message_id}`);
      invariant(!eventById.has(edge.event_id), `Duplicate event ID: ${edge.event_id}`);
      const record = { ...edge, requirement_id: requirementGraph.requirement_id, graph_index: graphIndex, edge_index: edgeIndex };
      eventById.set(edge.event_id, record);
      events.push(record);
    });
  });

  events.sort((left, right) => (
    messageOrder.get(left.source_message_id) - messageOrder.get(right.source_message_id)
    || left.graph_index - right.graph_index
    || left.edge_index - right.edge_index
  ));
  return { messageOrder, graphByRequirement, stateById, eventById, events };
}

function replayTimeline(goldData, indexes) {
  const goldByMessage = new Map();
  for (const target of goldData.task_gold_states) {
    const messageId = target.target_task.source_message_id;
    invariant(!goldByMessage.has(messageId), `Multiple targets at message ${messageId} are not supported`);
    goldByMessage.set(messageId, target);
    for (const eventId of target.task_event_ids) {
      const event = indexes.eventById.get(eventId);
      invariant(event, `Gold target ${target.target_id} references unknown event ${eventId}`);
      invariant(event.source_message_id === messageId, `Gold event ${eventId} is not sourced from target message ${messageId}`);
    }
  }

  const groups = [];
  for (const event of indexes.events) {
    const previous = groups.at(-1);
    if (!previous || previous.message_id !== event.source_message_id) groups.push({ message_id: event.source_message_id, events: [] });
    groups.at(-1).events.push(event);
  }

  const current = new Map();
  const targetSnapshots = new Map();
  const ledger = [];

  for (const group of groups) {
    const target = goldByMessage.get(group.message_id) ?? null;
    const before = copyStateMap(current);
    if (target) {
      assertSameStateMap(before, stateMapFromGold(target.pre_task_gold_state), `${target.target_id} pre-task`);
      targetSnapshots.set(target.target_id, before);
    }

    for (const event of group.events) {
      const observedFrom = current.get(event.requirement_id);
      if (event.from_state_id === null) invariant(observedFrom === undefined, `INTRODUCE/observed-history event ${event.event_id} found an existing state ${observedFrom}`);
      else invariant(observedFrom === event.from_state_id, `Transition mismatch for ${event.event_id}: expected ${event.from_state_id}, found ${observedFrom}`);
      invariant(indexes.stateById.has(event.to_state_id), `Event ${event.event_id} points to missing state ${event.to_state_id}`);
      current.set(event.requirement_id, event.to_state_id);
    }

    const after = copyStateMap(current);
    if (target) assertSameStateMap(after, stateMapFromGold(target.post_task_gold_state), `${target.target_id} post-task`);
    ledger.push({
      message_id: group.message_id,
      atomic: true,
      target_id: target?.target_id ?? null,
      events: group.events.map((event) => ({
        event_id: event.event_id,
        event_type: event.event_type,
        requirement_id: event.requirement_id,
        from_state_id: event.from_state_id,
        to_state_id: event.to_state_id,
      })),
      state_count_before: before.size,
      state_count_after: after.size,
      gold_pre_verified: Boolean(target),
      gold_post_verified: Boolean(target),
    });
  }

  invariant(targetSnapshots.size === goldData.task_gold_states.length, "Not every Gold target received a reconstructed pre-state snapshot");
  return { targetSnapshots, ledger };
}

function materializeFeatures(stateMap, indexes) {
  const records = [];
  const seenSlugs = new Set();
  for (const requirementGraph of indexes.graphByRequirement.values()) {
    const stateId = stateMap.get(requirementGraph.requirement_id);
    if (!stateId) continue;
    const indexed = indexes.stateById.get(stateId);
    invariant(indexed?.requirementGraph.requirement_id === requirementGraph.requirement_id, `State ${stateId} belongs to the wrong requirement`);
    if (!isCodeProjected(requirementGraph, indexed.stateNode)) continue;
    const descriptor = featureDescriptor(requirementGraph, indexed.stateNode);
    invariant(!seenSlugs.has(descriptor.key), `Feature slug collision: ${descriptor.key}`);
    seenSlugs.add(descriptor.key);
    records.push({ requirementGraph, stateNode: indexed.stateNode, descriptor });
  }
  return records.sort((left, right) => left.descriptor.key.localeCompare(right.descriptor.key, "en"));
}

function requirementMappings(stateMap, indexes) {
  const mappings = [];
  for (const requirementGraph of indexes.graphByRequirement.values()) {
    const stateId = stateMap.get(requirementGraph.requirement_id);
    if (!stateId) continue;
    const stateNode = indexes.stateById.get(stateId).stateNode;
    const lifecycle = lifecycleOf(stateNode);
    const projected = isCodeProjected(requirementGraph, stateNode);
    const slug = slugify(requirementGraph.title);
    mappings.push({
      requirement_id: requirementGraph.requirement_id,
      state_id: stateId,
      lifecycle,
      components: stateNode.scope?.components ?? [],
      implementation_mode: projected
        ? "simulated_executable"
        : NON_CODE_REQUIREMENT_IDS.has(requirementGraph.requirement_id)
          ? "non_code_external_action"
          : "excluded_lifecycle",
      code_paths: projected ? [
        `apps/site/src/features/${slug}.mjs`,
        "apps/site/src/runtime.mjs",
        "apps/site/public/app.js",
      ] : [],
    });
  }
  return mappings;
}

function createCenv(indexes, checksums) {
  const bundleName = `${PROJECT_ID}_C_env_complete`;
  const stageRoot = path.join(OUTPUTS.cenv, bundleName);
  const projectRoot = path.join(stageRoot, "project");
  const auditRoot = path.join(stageRoot, "reconstruction_audit");
  createRunnableRepository(projectRoot, {
    features: [],
    environmentLabel: "completed-zero-domain-baseline",
    repositoryLabel: `${PROJECT_ID} Completed Zero-Domain Website Baseline`,
  });
  const runtimeValidation = validateRunnableRepository(projectRoot);
  const leakageFindings = scanTextFiles(projectRoot, CENV_FORBIDDEN_PATTERNS);
  const secretFindings = scanTextFiles(projectRoot, SECRET_PATTERNS);
  invariant(leakageFindings.length === 0, `C_env contains future-domain terms: ${JSON.stringify(leakageFindings)}`);
  invariant(secretFindings.length === 0, `C_env contains possible credentials or PII: ${JSON.stringify(secretFindings)}`);
  const projectSha = sha256Tree(projectRoot);

  writeJson(path.join(auditRoot, "artifact_decisions.json"), {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    historical_source_status: "not-present-in-local-corpus",
    observed_repository_topology: ["WordPress website", "Elementor-authored responsive pages", "staging-to-hosting deployment workflow"],
    chosen_executable_substrate: "dependency-free Node.js responsive website behavior harness",
    rationale: "The chat and annotations establish a WordPress/Elementor website but do not provide a frozen theme, plugin, database export, or media archive. A runnable behavioral substrate is therefore used without claiming byte-level or CMS-build fidelity.",
    boundary_policy: "The C_env project contains the completed generic scaffold and zero project-specific business capabilities.",
    external_services: "No external network service is required; observable behavior is local and deterministic.",
    sensitive_source_handling: "Hosting URLs, admin paths, usernames, passwords, email addresses, and unredacted chat content are excluded from every exported repository.",
  });
  writeJson(path.join(auditRoot, "cenv_manifest.json"), {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    baseline_type: "simulated",
    repository_classification: "completed-zero-domain-baseline",
    contract_layer: "observed-wordpress-elementor-topology-plus-simulated-executable-harness",
    project_sha256: projectSha,
    source_artifact_checksums: checksums,
    toolchain: {
      observed: ["WordPress website referenced in the job and chat", "Elementor behavior referenced in the chat", "responsive desktop/tablet/mobile staging site claimed in chat"],
      executable_reconstruction: [process.version, "npm lockfile v3", "Node.js standard library only"],
    },
    commands: ["npm ci --ignore-scripts", "npm run check", "npm start"],
    limitations: [
      "The unavailable WordPress theme/plugins, database, uploads, and hosting snapshot are not fabricated.",
      "CMS and responsive browser behavior is represented through a deterministic local harness, not a recovered WordPress installation.",
    ],
  });
  writeJson(path.join(auditRoot, "validation_report.json"), {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    overall: "PASS",
    runtime_validation: runtimeValidation,
    zero_domain_leakage_scan: { status: "PASS", finding_count: 0, rules: CENV_FORBIDDEN_PATTERNS.map((item) => item.name) },
    secret_and_pii_scan: { status: "PASS", finding_count: 0, rules: SECRET_PATTERNS.map((item) => item.name) },
  });

  const archivePath = path.join(OUTPUTS.cenv, `${bundleName}.zip`);
  createDeterministicZip(stageRoot, archivePath, bundleName);
  const archiveValidation = validateZip(archivePath);
  fs.rmSync(stageRoot, { recursive: true, force: true });
  return { bundleName, archivePath, projectSha, runtimeValidation, archiveValidation };
}

function createTarget(target, stateMap, indexes) {
  const messageId = target.target_task.source_message_id;
  const targetShortId = target.target_id.replace(`${PROJECT_ID}_`, "");
  const targetRoot = path.join(OUTPUTS.targets, `${targetShortId}_before_${messageId}`);
  const repositoryRoot = path.join(targetRoot, "pre_repo");
  const features = materializeFeatures(stateMap, indexes);
  createRunnableRepository(repositoryRoot, {
    features,
    environmentLabel: "reconstructed-pre-event",
    repositoryLabel: `${PROJECT_ID} Reconstructed Website Pre-Event Repository`,
  });
  const runtimeValidation = validateRunnableRepository(repositoryRoot);
  const secretFindings = scanTextFiles(repositoryRoot, SECRET_PATTERNS);
  invariant(secretFindings.length === 0, `${target.target_id} contains possible credentials or PII: ${JSON.stringify(secretFindings)}`);
  const repoSha = sha256Tree(repositoryRoot);
  const archivePath = path.join(targetRoot, "pre_repo.zip");
  createDeterministicZip(repositoryRoot, archivePath);
  const archiveValidation = validateZip(archivePath);
  const targetEvents = target.task_event_ids.map((eventId) => indexes.eventById.get(eventId));
  invariant(targetEvents.every(Boolean), `${target.target_id} contains unknown events`);
  const mappings = requirementMappings(stateMap, indexes);
  const targetEventTypes = targetEvents.map((event) => event.event_type);
  const rq4Eligible = target.primary_rq_targets.includes("RQ4");
  const targetActionability = targetEventTypes.every((eventType) => eventType === "AMBIGUOUS")
    ? "clarification-required-no-code-mutation"
    : rq4Eligible
      ? "rq4-executable-change"
      : "state-transition-not-selected-for-rq4";
  const manifest = {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    target_id: target.target_id,
    before_message_id: messageId,
    repository_classification: "simulated-executable-pre-state",
    contract_layer: "observed-wordpress-elementor-topology-plus-simulated-state-model",
    web_api_layer: "local-responsive-site-harness-derived-from-chat-and-state-graph",
    active_code_feature_count: features.length,
    tracked_requirement_count: stateMap.size,
    temporal_fixture: null,
    primary_rq_targets: [...target.primary_rq_targets],
    rq4_eligible: rq4Eligible,
    target_actionability: targetActionability,
    requirements_to_code: mappings,
    target_event_ids: [...target.task_event_ids],
    target_event_types: targetEventTypes,
    target_summary: target.target_task.text,
    pre_state_verified_against_gold: true,
    post_state_verified_against_gold: true,
    repo_sha256: repoSha,
  };
  writeJson(path.join(targetRoot, "manifest.json"), manifest);
  return {
    manifest,
    targetRoot,
    repositoryRoot,
    runtimeValidation,
    secretScan: { status: "PASS", finding_count: 0, rules: SECRET_PATTERNS.map((item) => item.name) },
    archiveValidation,
  };
}

function writeReports({ requirementData, goldData, checksums, replay, cenvResult, targetResults, indexes }) {
  const targetIndex = targetResults.map((result) => ({ ...result.manifest }));
  const rq4TargetIds = targetResults.filter((result) => result.manifest.rq4_eligible).map((result) => result.manifest.target_id);
  writeJson(path.join(OUTPUTS.reports, "source_checksums.json"), {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    artifacts: checksums,
  });
  writeJson(path.join(OUTPUTS.reports, "replay_manifest.json"), {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    replay_policy: "All requirement events sharing a source message are applied atomically in graph/edge order.",
    requirement_count: requirementData.requirement_graphs.length,
    event_count: indexes.events.length,
    target_count: goldData.task_gold_states.length,
    all_target_pre_states_verified: true,
    all_target_post_states_verified: true,
    ledger: replay.ledger,
  });
  writeJson(path.join(OUTPUTS.reports, "target_index.json"), targetIndex);
  writeJson(path.join(OUTPUTS.reports, "validation_report.json"), {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    overall: "PASS",
    reconstruction_classification: "simulated-executable",
    c_env: {
      status: "PASS",
      project_sha256: cenvResult.projectSha,
      runtime_validation: cenvResult.runtimeValidation,
      archive_validation: cenvResult.archiveValidation,
      zero_domain_leakage_scan: { status: "PASS", finding_count: 0 },
      secret_and_pii_scan: { status: "PASS", finding_count: 0 },
    },
    replay: {
      status: "PASS",
      event_group_count: replay.ledger.length,
      target_count: targetResults.length,
      pre_state_gold_matches: targetResults.length,
      post_state_gold_matches: targetResults.length,
    },
    targets: targetResults.map((result) => ({
      target_id: result.manifest.target_id,
      before_message_id: result.manifest.before_message_id,
      status: "PASS",
      repo_sha256: result.manifest.repo_sha256,
      runtime_validation: result.runtimeValidation,
      archive_validation: result.archiveValidation,
      secret_and_pii_scan: result.secretScan,
    })),
    loader_contract: {
      status: "PASS",
      exact_target_set: true,
      event_ids_and_types_match_gold_graph: true,
      manifest_index_fields_match: true,
      all_archives_safe_and_crc_verified: true,
    },
  });

  writeText(path.join(OUTPUTS.reports, "reconstruction_report.md"), `# ${PROJECT_ID} reconstruction report

## Outcome

The package contains one completed zero-domain baseline and ${targetResults.length} independently runnable repositories representing the exact state immediately before every selected target message. Every requirement event was replayed atomically by source message, and every target boundary matched both the pre-task and post-task Gold state.

${rq4TargetIds.length} of the ${targetResults.length} selected targets are marked for RQ4 by the Gold data (${rq4TargetIds.join(", ")}). Every selected snapshot is retained so that the temporal replay remains complete and auditable.

## Fidelity boundary

The local corpus describes a WordPress/Elementor website and its responsive behavior, but it does not contain a frozen historical theme, plugin set, database, uploads archive, or hosting snapshot. The package therefore uses a deterministic, dependency-free Node.js behavior harness. It is an executable state reconstruction, not a claim that the original CMS files were recovered.

The Requirement State Graph contains ${requirementData.requirement_graphs.length} requirements and ${indexes.events.length} events. Only graph-backed states are projected; hosting credentials, the live domain, and raw chat content are never copied into a repository.

## Verification

- Clean install: \`npm ci --ignore-scripts\`
- Syntax, build, and endpoint tests: \`npm run check\`
- C_env project-specific future-state leakage scan: PASS
- C_env and target credential/PII scans: PASS
- Gold pre-state and post-state comparisons: ${targetResults.length}/${targetResults.length} PASS
- ZIP CRC, safe-path, no-symlink, and no-\`.git\` checks: PASS

See \`validation_report.json\`, \`replay_manifest.json\`, \`independent_audit_report.json\` (created by the independent audit), and each target's \`manifest.json\` for machine-readable evidence.
`);

  writeText(path.join(PACKAGE_ROOT, "README.md"), `# ${PROJECT_ID} Reconstruction Package

Start with \`reports/reconstruction_report.md\`.

- \`C_env/${PROJECT_ID}_C_env_complete.zip\`: completed zero-domain executable baseline.
- \`targets/Txxx_before_<message>/pre_repo.zip\`: runnable pre-event repository.
- \`targets/.../manifest.json\`: state-to-code mapping and boundary audit.
- \`reports/replay_manifest.json\`: complete atomic event replay ledger.
- \`reports/validation_report.json\`: build, test, leakage, archive, and credential checks.
- \`tools/reconstruct_all.mjs\`: deterministic reconstruction generator.
- \`tools/audit_outputs.mjs\`: independent archive, Gold-contract, tree-hash, and semantic audit.
`);
}

for (const directory of Object.values(OUTPUTS)) safeResetDirectory(directory);
const checksums = sourceChecksums();
const requirementData = readJson(INPUTS.requirementGraph);
const goldData = readJson(INPUTS.goldStates);
const normalizedProject = readJson(INPUTS.normalizedProject);
invariant(String(requirementData.project_id) === PROJECT_ID, "Requirement graph project ID mismatch");
invariant(String(goldData.project_id) === PROJECT_ID, "Gold state project ID mismatch");
invariant(String(normalizedProject.project_id) === PROJECT_ID, "Normalized project ID mismatch");
const indexes = buildIndexes(requirementData, normalizedProject);
const replay = replayTimeline(goldData, indexes);
const cenvResult = createCenv(indexes, checksums);
const targetResults = [];
for (const target of goldData.task_gold_states) {
  process.stdout.write(`Reconstructing ${target.target_id} before message ${target.target_task.source_message_id}...\n`);
  targetResults.push(createTarget(target, replay.targetSnapshots.get(target.target_id), indexes));
}
writeReports({ requirementData, goldData, checksums, replay, cenvResult, targetResults, indexes });
process.stdout.write(`PASS: reconstructed ${PROJECT_ID} C_env and ${targetResults.length} pre-event repositories.\n`);
