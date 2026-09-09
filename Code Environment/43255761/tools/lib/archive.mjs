import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

export const EXCLUDED_TREE_PARTS = new Set(["node_modules", "out", "cache", "dist", ".git", "__pycache__", ".render-qa"]);
const FIXED_DOS_TIME = 0;
const FIXED_DOS_DATE = 33;

export function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

export function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

export function jsonText(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

export function writeText(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content, "utf8");
}

export function writeJson(filePath, value) {
  writeText(filePath, jsonText(value));
}

export function sha256Buffer(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

export function sha256File(filePath) {
  return sha256Buffer(fs.readFileSync(filePath));
}

export function toPosix(value) {
  return value.split(path.sep).join("/");
}

export function listFiles(root, { applyTreeExclusions = false } = {}) {
  const files = [];
  function visit(current) {
    const entries = fs.readdirSync(current, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name, "en"));
    for (const entry of entries) {
      const absolute = path.join(current, entry.name);
      const relative = path.relative(root, absolute);
      if (applyTreeExclusions && relative.split(path.sep).some((part) => EXCLUDED_TREE_PARTS.has(part))) continue;
      invariant(!entry.isSymbolicLink(), `Symbolic links are forbidden: ${absolute}`);
      if (entry.isDirectory()) visit(absolute);
      else if (entry.isFile()) files.push({ absolute, relative: toPosix(relative) });
      else throw new Error(`Unsupported filesystem entry: ${absolute}`);
    }
  }
  visit(root);
  return files.sort((a, b) => a.relative.localeCompare(b.relative, "en"));
}

export function sha256Tree(root) {
  const hash = crypto.createHash("sha256");
  for (const file of listFiles(root, { applyTreeExclusions: true })) {
    hash.update(Buffer.from(file.relative, "utf8"));
    hash.update(Buffer.from([0]));
    hash.update(fs.readFileSync(file.absolute));
    hash.update(Buffer.from([0]));
  }
  return hash.digest("hex");
}

export function resetOwnedDirectory(directoryPath, packageRoot, allowedDirectories) {
  const resolved = path.resolve(directoryPath);
  invariant(path.dirname(resolved) === path.resolve(packageRoot), `Refusing to reset outside package root: ${resolved}`);
  invariant(new Set(allowedDirectories.map((item) => path.resolve(item))).has(resolved), `Unexpected reset target: ${resolved}`);
  fs.rmSync(resolved, { recursive: true, force: true });
  fs.mkdirSync(resolved, { recursive: true });
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

export function crc32(buffer) {
  let value = 0xffffffff;
  for (const byte of buffer) value = CRC32_TABLE[(value ^ byte) & 0xff] ^ (value >>> 8);
  return (value ^ 0xffffffff) >>> 0;
}

export function zipPathIsSafe(entryName) {
  if (!entryName || entryName.includes("\\") || entryName.startsWith("/") || /^[A-Za-z]:/.test(entryName)) return false;
  const parts = entryName.split("/");
  return !parts.some((part) => part === ".." || part.toLowerCase() === ".git");
}

export function createDeterministicZip(sourceRoot, archivePath, rootPrefix = "") {
  const files = listFiles(sourceRoot, { applyTreeExclusions: true });
  invariant(files.length > 0, `Refusing to create an empty archive: ${archivePath}`);
  const localRecords = [];
  const centralRecords = [];
  let offset = 0;
  for (const file of files) {
    const entryName = rootPrefix ? `${rootPrefix.replace(/\/$/, "")}/${file.relative}` : file.relative;
    invariant(zipPathIsSafe(entryName), `Unsafe archive path: ${entryName}`);
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

function findEocd(archive) {
  for (let offset = archive.length - 22; offset >= Math.max(0, archive.length - 65557); offset -= 1) {
    if (archive.readUInt32LE(offset) === 0x06054b50) return offset;
  }
  return -1;
}

export function readZipEntries(archiveOrPath) {
  const archive = Buffer.isBuffer(archiveOrPath) ? archiveOrPath : fs.readFileSync(archiveOrPath);
  const eocdOffset = findEocd(archive);
  invariant(eocdOffset >= 0, "ZIP end-of-central-directory record not found");
  const entryCount = archive.readUInt16LE(eocdOffset + 10);
  let cursor = archive.readUInt32LE(eocdOffset + 16);
  const entries = new Map();
  for (let index = 0; index < entryCount; index += 1) {
    invariant(archive.readUInt32LE(cursor) === 0x02014b50, `Invalid central directory entry ${index}`);
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
    invariant(zipPathIsSafe(entryName), `Unsafe ZIP member: ${entryName}`);
    invariant((((externalAttributes >>> 16) & 0xffff) & 0o170000) !== 0o120000, `Symlink ZIP member: ${entryName}`);
    invariant(archive.readUInt32LE(localOffset) === 0x04034b50, `Missing local header: ${entryName}`);
    const localNameLength = archive.readUInt16LE(localOffset + 26);
    const localExtraLength = archive.readUInt16LE(localOffset + 28);
    const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = archive.subarray(dataOffset, dataOffset + compressedSize);
    const raw = method === 8 ? zlib.inflateRawSync(compressed) : method === 0 ? compressed : null;
    invariant(raw, `Unsupported ZIP method ${method}: ${entryName}`);
    invariant(raw.length === uncompressedSize, `ZIP size mismatch: ${entryName}`);
    invariant(crc32(raw) === expectedCrc, `ZIP CRC mismatch: ${entryName}`);
    invariant(!entries.has(entryName), `Duplicate ZIP member: ${entryName}`);
    entries.set(entryName, raw);
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  invariant(entries.size === entryCount && entryCount > 0, "Invalid or empty ZIP archive");
  return entries;
}

export function validateZip(archivePath) {
  const archive = fs.readFileSync(archivePath);
  const entries = readZipEntries(archive);
  return {
    status: "PASS",
    archive_sha256: sha256Buffer(archive),
    archive_bytes: archive.length,
    entry_count: entries.size,
    uncompressed_bytes: [...entries.values()].reduce((sum, item) => sum + item.length, 0),
    safe_paths: true,
    crc_verified: true,
    symlink_free: true,
    git_metadata_free: true,
  };
}

function quoteWindowsArg(value) {
  const text = String(value);
  if (!/[\s"]/u.test(text)) return text;
  return `"${text.replace(/(\\*)"/g, "$1$1\\\"").replace(/(\\+)$/g, "$1$1")}"`;
}

export function runCommand(cwd, executable, args) {
  const shown = [executable, ...args].join(" ");
  let invokedExecutable = executable;
  let invokedArgs = args;
  if (process.platform === "win32" && executable.toLowerCase().endsWith(".cmd")) {
    invokedExecutable = process.env.ComSpec ?? "cmd.exe";
    invokedArgs = ["/d", "/s", "/c", [executable, ...args].map(quoteWindowsArg).join(" ")];
  }
  const result = spawnSync(invokedExecutable, invokedArgs, {
    cwd,
    encoding: "utf8",
    shell: false,
    env: { ...process.env, NO_COLOR: "1", npm_config_audit: "false", npm_config_fund: "false", npm_config_update_notifier: "false" },
  });
  invariant(result.status === 0, `${shown} failed in ${cwd}\n${result.stdout ?? ""}\n${result.stderr ?? ""}`);
  return { command: shown, status: "PASS", exit_code: result.status };
}

export function scanTextFiles(root, patterns) {
  const findings = [];
  for (const file of listFiles(root, { applyTreeExclusions: true })) {
    const bytes = fs.readFileSync(file.absolute);
    if (bytes.includes(0)) continue;
    const text = bytes.toString("utf8");
    for (const rule of patterns) {
      rule.regex.lastIndex = 0;
      if (rule.regex.test(text)) findings.push({ path: file.relative, rule: rule.name });
    }
  }
  return findings;
}
