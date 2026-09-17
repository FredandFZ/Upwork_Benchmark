import fs from "node:fs";
import path from "node:path";
import { invariant, jsonText, writeText } from "./archive.mjs";

export function slugify(value) {
  const slug = String(value).normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").replace(/-{2,}/g, "-");
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

function numberFrom(value, fallback = null) {
  if (Number.isFinite(value)) return value;
  const match = String(value ?? "").match(/\b(\d+(?:\.\d+)?)\b/);
  return match ? Number(match[1]) : fallback;
}

export function renderHints(requirementId, stateNode) {
  const attributes = stateNode.attributes ?? {};
  const text = stringsDeep(attributes).join(" | ");
  const hints = {};
  if (requirementId === "REQ_PCB_ARCHITECTURE_VARIANTS") {
    hints.projectTitle = "Embedded Hardware Platform";
    hints.boardVariant = text.slice(0, 120) || "graph-specified-variant";
    if (/three[- ]board|separate power.*main.*sensor/i.test(text)) hints.boardCount = 3;
    else if (/integrated|single[- ]board/i.test(text)) hints.boardCount = 1;
  }
  if (requirementId === "REQ_POWER_BOARD_MECHANICAL_FORM_FACTOR" || requirementId === "REQ_MAIN_BOARD_ROUTABLE_FORM_FACTOR" || requirementId === "REQ_SENSOR_BOARD_ROUTABLE_FORM_FACTOR") {
    if (Number.isFinite(attributes.mounting_hole_count)) hints.mountingHoleCount = attributes.mounting_hole_count;
    if (Array.isArray(attributes.board_dimensions_mm) && attributes.board_dimensions_mm.length >= 2) {
      hints.boardWidthMm = numberFrom(attributes.board_dimensions_mm[0], 80);
      hints.boardHeightMm = numberFrom(attributes.board_dimensions_mm[1], 50);
    }
  }
  if (requirementId === "REQ_SEPARATE_BOARD_CONNECTOR_LAYOUT") {
    hints.connectorTopAligned = /top edge|top-edge/.test(text.toLowerCase()) && /align/.test(text.toLowerCase());
    hints.lowerConnectorsUpward = /lower_connector_orientation/.test(JSON.stringify(attributes)) && /upward/i.test(text);
  }
  if (requirementId === "REQ_BATTERY_SAFETY_PROTECTION") {
    hints.batteryProtectionSpecified = attributes.battery_protection_required === true || /overcharge|overdischarge|protection/i.test(text);
    hints.overchargeCutoffSpecified = typeof attributes.overcharge_protection === "string";
  }
  if (requirementId === "REQ_BATTERY_CONNECTOR_INTERFACE") {
    hints.batteryNtcContact = attributes.ntc_contact_required === true || /\bNTC\b/i.test(text);
    if (typeof attributes.battery_jst_orientation === "string") hints.batteryConnectorOrientation = attributes.battery_jst_orientation;
  }
  if (requirementId === "REQ_ESP32_FULL_PIN_BREAKOUT") {
    hints.fullPinBreakout = /every|full/i.test(String(attributes.pin_coverage ?? text));
    hints.throughHoleBreakout = /through[- ]hole/i.test(String(attributes.breakout_format ?? text));
    const pinCount = text.match(/\b(40|44)[- ]pin\b/i);
    if (pinCount) hints.breakoutPinCount = Number(pinCount[1]);
  }
  if (requirementId === "REQ_BOM_ASSEMBLY_READINESS") hints.bomStatus = stateNode.execution?.status === "FAILED" ? "failed" : "specified";
  if (requirementId === "REQ_TOUCH_INPUT_INTERFACES") {
    hints.touchInputCount = Array.isArray(attributes.touch_inputs) ? attributes.touch_inputs.length : numberFrom(attributes.touch_input_count, 1);
    hints.inputBiasSpecified = Boolean(attributes.bias_resistors);
  }
  if (requirementId === "REQ_PIR_INPUT_INTERFACE") {
    hints.pirInputPresent = attributes.pir_connector_provided !== false;
    if (attributes.bias_configuration) hints.inputBiasSpecified = true;
  }
  if (requirementId === "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS") {
    hints.panelInputCount = [attributes.button_3, attributes.button_4, attributes.slide_switch].filter(Boolean).length || numberFrom(attributes.input_count, 1);
    if (attributes.input_bias) hints.inputBiasSpecified = true;
  }
  if (requirementId === "REQ_AXP_VRTC_HANDLING") hints.vrtcHandling = String(attributes.vrtc_connection ?? "specified");
  if (requirementId === "REQ_AXP_VBACKUP_ACCESS") {
    hints.vbackupAccess = /pad|via|access/i.test(text);
    hints.vbackupLocationSpecified = typeof attributes.access_location === "string";
  }
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

function snapshotSource(features, environmentLabel) {
  const imports = features.map((feature, index) => `import feature${String(index + 1).padStart(3, "0")} from "./features/${feature.key}.mjs";`).join("\n");
  const names = features.map((_, index) => `feature${String(index + 1).padStart(3, "0")}`).join(", ");
  return `${imports}${imports ? "\n" : ""}import { buildProfile } from "./profile.mjs";\n\nconst features = Object.freeze([${names}]);\nconst stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));\n\nexport const profile = buildProfile(features);\nexport const snapshot = Object.freeze({ environment: ${JSON.stringify(environmentLabel)}, features, stateMap });\n`;
}

function readme(repositoryLabel, featureCount) {
  return `# ${repositoryLabel}\n\nThis repository is a deterministic executable temporal reconstruction, not a recovered historical KiCad repository. Final delivered project assets are checksum evidence only and are never used to seed a pre-event state.\n\nIt uses the Node.js standard library to generate KiCad-compatible board and schematic fixtures plus an exact design-state artifact. Behavior-level operations expose the projected mechanical, connector, breakout, power-safety, input-interface, and manufacturing state.\n\n## Run\n\n\`\`\`sh\nnpm ci --ignore-scripts\nnpm run check\nnpm run inspect\n\`\`\`\n\nThe snapshot contains ${featureCount} projected requirement states. Node.js 20 or newer is required. KiCad is optional for manual viewing and is not required for deterministic build or validation.\n`;
}

export function createKicadRepository(destination, templateRoot, { features, environmentLabel, repositoryLabel }) {
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
  writeText(path.join(destination, "src", "snapshot.mjs"), snapshotSource(features, environmentLabel));
  writeText(path.join(destination, "README.md"), readme(repositoryLabel, features.length));
  writeText(path.join(destination, "reconstruction-contract.json"), jsonText({
    schema_version: "1.0",
    environment: environmentLabel,
    repository_classification: features.length === 0 ? "completed-zero-domain-baseline" : "simulated-executable-pre-state",
    projected_requirement_count: features.length,
    source_policy: "Graph-backed synthetic KiCad fixtures; final deliverable tree is checksum-only evidence and is not a temporal seed.",
  }));
}
