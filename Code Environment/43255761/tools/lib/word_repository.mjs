import fs from "node:fs";
import path from "node:path";
import { invariant, jsonText, writeText } from "./archive.mjs";

export function slugify(value) {
  const slug = String(value)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-");
  invariant(slug.length > 0, `Unable to derive slug from ${value}`);
  return slug;
}

function lifecycleOf(stateNode) {
  return stateNode.lifecycle_status ?? "OBSERVED";
}

function stringsDeep(value) {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(stringsDeep);
  if (value && typeof value === "object") return Object.values(value).flatMap(stringsDeep);
  return [];
}

function parseTitleHalfPoints(attributes) {
  const value = attributes?.title_font_size;
  if (typeof value !== "string") return null;
  const match = value.match(/([0-9]+(?:\.[0-9]+)?)\s*pt\b/i);
  return match ? Math.round(Number(match[1]) * 2) : null;
}

function firstHex(attributes) {
  for (const value of stringsDeep(attributes)) {
    const match = value.match(/#([0-9a-f]{6})\b/i);
    if (match) return match[1].toUpperCase();
  }
  return null;
}

export function renderHints(requirementId, stateNode) {
  const attributes = stateNode.attributes ?? {};
  const hints = {};
  if (requirementId === "REQ_DANISH_LANGUAGE_CONFIGURATION" && /danish/i.test(String(attributes.document_content_language ?? ""))) {
    hints.documentLanguage = "da-DK";
  }
  if (requirementId === "REQ_STYLE_TYPOGRAPHY") {
    const titleHalfPoints = parseTitleHalfPoints(attributes);
    if (titleHalfPoints !== null) hints.titleHalfPoints = titleHalfPoints;
  }
  if (requirementId === "REQ_BULLET_VISUAL_FORMATTING") {
    hints.bulletApproved = Object.hasOwn(attributes, "approved_appearance");
  }
  if (requirementId === "REQ_STYLE_NAMING" && typeof attributes.style_name_prefix === "string") {
    hints.stylePrefix = attributes.style_name_prefix;
  }
  if (requirementId === "REQ_BOARD_MEETING_FIELD_ALIGNMENT") {
    const topic = typeof attributes.topic_field_label === "string" ? attributes.topic_field_label : "Topic";
    hints.formRows = ["Item and Title", topic, "Proposal", "Start time"];
    hints.firstRowIndentDxa = stateNode.execution?.status === "FAILED" ? 360 : 0;
  }
  const accentHex = firstHex(attributes);
  if (requirementId === "REQ_THEME_COLOR_PALETTE" && accentHex) hints.accentHex = accentHex;
  return hints;
}

export function featureDescriptor(requirementGraph, stateNode) {
  return {
    requirement_id: requirementGraph.requirement_id,
    state_id: stateNode.state_id,
    key: slugify(requirementGraph.title),
    title: requirementGraph.title,
    family: requirementGraph.family_id,
    lifecycle: lifecycleOf(stateNode),
    components: stateNode.scope?.components ?? [],
    contexts: stateNode.scope?.contexts ?? [],
    attributes: stateNode.attributes ?? {},
    ambiguity: stateNode.ambiguity ?? null,
    execution: stateNode.execution ?? null,
    supporting_event_ids: stateNode.supporting_event_ids ?? [],
    render_hints: renderHints(requirementGraph.requirement_id, stateNode),
  };
}

export function isProjected(stateNode) {
  return !new Set(["REMOVED", "DEFERRED"]).has(lifecycleOf(stateNode));
}

function identifier(index) {
  return `feature${String(index + 1).padStart(3, "0")}`;
}

function snapshotSource(features, environmentLabel, documentLabel) {
  const imports = features.map((feature, index) => `import ${identifier(index)} from "./features/${feature.key}.mjs";`).join("\n");
  const names = features.map((_, index) => identifier(index)).join(", ");
  return `${imports}${imports ? "\n" : ""}import { buildProfile } from "./profile.mjs";\n\nconst features = Object.freeze([${names}]);\nconst stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));\n\nexport const profile = buildProfile(features);\nexport const snapshot = Object.freeze({\n  environment: ${JSON.stringify(environmentLabel)},\n  documentLabel: ${JSON.stringify(documentLabel)},\n  features,\n  stateMap,\n});\n`;
}

function readme(repositoryLabel, featureCount) {
  return `# ${repositoryLabel}\n\nThis is a deterministic executable reconstruction of a Word-template state. It is not a recovered historical source repository and it does not seed any pre-event state from the final delivered DOCX files.\n\nThe repository uses the Node.js standard library only. It generates a real macro-free OOXML \`.docx\`, exposes behavior-level title/list/field operations, and keeps one graph-backed module per active requirement state.\n\n## Run\n\n\`\`\`sh\nnpm ci --ignore-scripts\nnpm run check\nnpm run inspect\n\`\`\`\n\nThe generated artifact is \`artifacts/reconstructed-template.docx\`. The current snapshot contains ${featureCount} projected requirement states. Node.js 20 or newer is required; no network service, Microsoft Office installation, or credential is needed for build and test.\n`;
}

export function createWordRepository(destination, templateRoot, { features, environmentLabel, repositoryLabel, documentLabel }) {
  fs.mkdirSync(destination, { recursive: true });
  fs.cpSync(templateRoot, destination, { recursive: true, force: false, errorOnExist: false });
  const featureRoot = path.join(destination, "src", "features");
  fs.mkdirSync(featureRoot, { recursive: true });
  const seen = new Set();
  for (const feature of features) {
    invariant(!seen.has(feature.key), `Feature slug collision: ${feature.key}`);
    seen.add(feature.key);
    writeText(path.join(featureRoot, `${feature.key}.mjs`), `export default Object.freeze(${JSON.stringify(feature, null, 2)});\n`);
  }
  writeText(path.join(destination, "src", "snapshot.mjs"), snapshotSource(features, environmentLabel, documentLabel));
  writeText(path.join(destination, "README.md"), readme(repositoryLabel, features.length));
  writeText(path.join(destination, "reconstruction-contract.json"), jsonText({
    schema_version: "1.0",
    environment: environmentLabel,
    repository_classification: features.length === 0 ? "completed-zero-domain-baseline" : "simulated-executable-pre-state",
    projected_requirement_count: features.length,
    source_policy: "Graph-backed synthetic OOXML; final deliverable DOCX files are checksum-only evidence and are not temporal seeds.",
  }));
}
