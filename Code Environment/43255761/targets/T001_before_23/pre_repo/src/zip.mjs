import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

const DOS_TIME = 0;
const DOS_DATE = 33;

function invariant(condition, message) {
  if (!condition) throw new Error(message);
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

const CRC_TABLE = crc32Table();

export function crc32(buffer) {
  let value = 0xffffffff;
  for (const byte of buffer) value = CRC_TABLE[(value ^ byte) & 0xff] ^ (value >>> 8);
  return (value ^ 0xffffffff) >>> 0;
}

function safeName(name) {
  return Boolean(name)
    && !name.includes("\\")
    && !name.startsWith("/")
    && !/^[A-Za-z]:/.test(name)
    && !name.split("/").some((part) => part === ".." || part.toLowerCase() === ".git");
}

export function zipEntries(entries) {
  const normalized = [...entries.entries()]
    .map(([name, value]) => [name, Buffer.isBuffer(value) ? value : Buffer.from(value, "utf8")])
    .sort(([left], [right]) => left.localeCompare(right, "en"));
  invariant(normalized.length > 0, "Cannot create an empty ZIP archive");
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const [entryName, raw] of normalized) {
    invariant(safeName(entryName), `Unsafe ZIP path: ${entryName}`);
    const name = Buffer.from(entryName, "utf8");
    const compressed = zlib.deflateRawSync(raw, { level: 9 });
    const checksum = crc32(raw);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x0800, 6);
    local.writeUInt16LE(8, 8);
    local.writeUInt16LE(DOS_TIME, 10);
    local.writeUInt16LE(DOS_DATE, 12);
    local.writeUInt32LE(checksum, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(raw.length, 22);
    local.writeUInt16LE(name.length, 26);
    locals.push(local, name, compressed);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE((3 << 8) | 20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt16LE(8, 10);
    central.writeUInt16LE(DOS_TIME, 12);
    central.writeUInt16LE(DOS_DATE, 14);
    central.writeUInt32LE(checksum, 16);
    central.writeUInt32LE(compressed.length, 20);
    central.writeUInt32LE(raw.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE((0o100644 << 16) >>> 0, 38);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, name);
    offset += local.length + name.length + compressed.length;
  }
  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(normalized.length, 8);
  end.writeUInt16LE(normalized.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

export function writeZip(filePath, entries) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, zipEntries(entries));
}

function findEnd(buffer) {
  for (let offset = buffer.length - 22; offset >= Math.max(0, buffer.length - 65557); offset -= 1) {
    if (buffer.readUInt32LE(offset) === 0x06054b50) return offset;
  }
  return -1;
}

export function readZip(fileOrBuffer) {
  const archive = Buffer.isBuffer(fileOrBuffer) ? fileOrBuffer : fs.readFileSync(fileOrBuffer);
  const endOffset = findEnd(archive);
  invariant(endOffset >= 0, "ZIP end record is missing");
  const count = archive.readUInt16LE(endOffset + 10);
  let cursor = archive.readUInt32LE(endOffset + 16);
  const entries = new Map();
  for (let index = 0; index < count; index += 1) {
    invariant(archive.readUInt32LE(cursor) === 0x02014b50, `Invalid ZIP entry ${index}`);
    const flags = archive.readUInt16LE(cursor + 8);
    const method = archive.readUInt16LE(cursor + 10);
    const expectedCrc = archive.readUInt32LE(cursor + 16);
    const compressedSize = archive.readUInt32LE(cursor + 20);
    const rawSize = archive.readUInt32LE(cursor + 24);
    const nameLength = archive.readUInt16LE(cursor + 28);
    const extraLength = archive.readUInt16LE(cursor + 30);
    const commentLength = archive.readUInt16LE(cursor + 32);
    const localOffset = archive.readUInt32LE(cursor + 42);
    const name = archive.subarray(cursor + 46, cursor + 46 + nameLength).toString((flags & 0x0800) ? "utf8" : "latin1");
    invariant(safeName(name), `Unsafe ZIP path: ${name}`);
    invariant(archive.readUInt32LE(localOffset) === 0x04034b50, `Missing local ZIP header: ${name}`);
    const localNameLength = archive.readUInt16LE(localOffset + 26);
    const localExtraLength = archive.readUInt16LE(localOffset + 28);
    const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = archive.subarray(dataOffset, dataOffset + compressedSize);
    const raw = method === 8 ? zlib.inflateRawSync(compressed) : method === 0 ? compressed : null;
    invariant(raw, `Unsupported ZIP method ${method}: ${name}`);
    invariant(raw.length === rawSize, `ZIP size mismatch: ${name}`);
    invariant(crc32(raw) === expectedCrc, `ZIP CRC mismatch: ${name}`);
    entries.set(name, raw);
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  invariant(entries.size === count && count > 0, "ZIP archive is empty or has duplicate entries");
  return entries;
}
