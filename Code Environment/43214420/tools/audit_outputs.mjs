#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const PROJECT_ID = "43214420";
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = path.resolve(SCRIPT_DIR, "..");
const WORKSPACE_ROOT = path.resolve(PACKAGE_ROOT, "..", "..");
const GRAPH_PATH = path.join(WORKSPACE_ROOT, "outputs", "stage2", PROJECT_ID, "requirement_state_graph.json");
const GOLD_PATH = path.join(WORKSPACE_ROOT, "outputs", "stage2", PROJECT_ID, "gold_states.json");
const NORMALIZED_PATH = path.join(WORKSPACE_ROOT, "outputs", "stage1_runs", PROJECT_ID, "normalized_project.json");
const FINAL_DELIVERABLE_ROOT = path.join(WORKSPACE_ROOT, "Datasets", "PII_clean_project", PROJECT_ID, "deliverables", "paid_18156583", "IoT_Environmental_Monitoring_Device_Power");
const CENV_ARCHIVE = path.join(PACKAGE_ROOT, "C_env", `${PROJECT_ID}_C_env_complete.zip`);
const TARGETS_ROOT = path.join(PACKAGE_ROOT, "targets");
const REPORTS_ROOT = path.join(PACKAGE_ROOT, "reports");
const TEMP_ROOT = path.join(PACKAGE_ROOT, ".independent-audit-tmp");
const EXCLUDED = new Set(["node_modules", "out", "cache", "dist", ".git", "__pycache__", ".render-qa"]);

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function toPosix(value) {
  return value.split(path.sep).join("/");
}

function listFiles(root) {
  const files = [];
  function visit(current) {
    for (const entry of fs.readdirSync(current, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name, "en"))) {
      const absolute = path.join(current, entry.name);
      const relative = path.relative(root, absolute);
      if (relative.split(path.sep).some((part) => EXCLUDED.has(part))) continue;
      assert.equal(entry.isSymbolicLink(), false, `Unexpected symlink: ${absolute}`);
      if (entry.isDirectory()) visit(absolute);
      else if (entry.isFile()) files.push({ absolute, relative: toPosix(relative) });
      else assert.fail(`Unsupported entry: ${absolute}`);
    }
  }
  visit(root);
  return files.sort((a, b) => a.relative.localeCompare(b.relative, "en"));
}

function treeHash(root) {
  const hash = crypto.createHash("sha256");
  for (const file of listFiles(root)) {
    hash.update(Buffer.from(file.relative, "utf8"));
    hash.update(Buffer.from([0]));
    hash.update(fs.readFileSync(file.absolute));
    hash.update(Buffer.from([0]));
  }
  return hash.digest("hex");
}

function run(executable, args, cwd = PACKAGE_ROOT) {
  const shown = [executable, ...args].join(" ");
  let invokedExecutable = executable;
  let invokedArgs = args;
  if (process.platform === "win32" && executable.toLowerCase().endsWith(".cmd")) {
    invokedExecutable = process.env.ComSpec ?? "cmd.exe";
    invokedArgs = ["/d", "/s", "/c", shown];
  }
  const result = spawnSync(invokedExecutable, invokedArgs, {
    cwd,
    encoding: "utf8",
    shell: false,
    env: { ...process.env, NO_COLOR: "1", npm_config_audit: "false", npm_config_fund: "false", npm_config_update_notifier: "false" },
  });
  assert.equal(result.status, 0, `${shown} failed in ${cwd}\n${result.stdout ?? ""}\n${result.stderr ?? ""}`);
  return { command: shown, status: "PASS" };
}

function archiveMembers(archivePath) {
  const result = spawnSync("tar", ["-tf", archivePath], { encoding: "utf8", shell: false });
  assert.equal(result.status, 0, `Unable to list ${archivePath}: ${result.stderr ?? ""}`);
  const members = result.stdout.split(/\r?\n/).filter(Boolean);
  assert.ok(members.length > 0, `Empty archive: ${archivePath}`);
  for (const member of members) {
    assert.equal(member.includes("\\"), false, `Backslash archive path: ${member}`);
    assert.equal(member.startsWith("/"), false, `Absolute archive path: ${member}`);
    assert.equal(/^[A-Za-z]:/.test(member), false, `Drive archive path: ${member}`);
    assert.equal(member.split("/").includes(".."), false, `Traversal archive path: ${member}`);
    assert.equal(member.split("/").some((part) => part.toLowerCase() === ".git"), false, `Git metadata: ${member}`);
  }
  const verbose = spawnSync("tar", ["-tvf", archivePath], { encoding: "utf8", shell: false });
  assert.equal(verbose.status, 0, `Unable to inspect modes: ${archivePath}`);
  for (const line of verbose.stdout.split(/\r?\n/).filter(Boolean)) assert.notEqual(line[0], "l", `Symlink archive member: ${line}`);
  return members;
}

function extractArchive(archivePath, destination) {
  fs.mkdirSync(destination, { recursive: true });
  archiveMembers(archivePath);
  run("tar", ["-xf", archivePath, "-C", destination]);
}

function assertNoSecrets(root) {
  const rules = [
    /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/i,
    /AKIA[0-9A-Z]{16}/,
    /gh[pousr]_[A-Za-z0-9]{30,}/,
    /xox[baprs]-[A-Za-z0-9-]{20,}/,
    /sk-[A-Za-z0-9_-]{32,}/,
    /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i,
    /(?:password|passwd|pwd)\s*[:=]\s*(?!placeholder|example|not-set)[^\s]{6,}/i,
    /\[(?:PASSWORD|ACCOUNT|EMAIL)_\d+\]/i,
  ];
  for (const file of listFiles(root)) {
    const bytes = fs.readFileSync(file.absolute);
    if (bytes.includes(0)) continue;
    for (const rule of rules) assert.equal(rule.test(bytes.toString("utf8")), false, `Possible secret/PII in ${file.relative}: ${rule}`);
  }
}

function assertZeroDomain(root) {
  const forbidden = [
    /\bIoT\b/i,
    /\bESP32(?:-S3)?\b/i,
    /\bAXP2101\b/i,
    /\bTTP223\b/i,
    /\bSPS30\b/i,
    /\bSK6812/i,
    /\bJLCPCB\b/i,
  ];
  for (const file of listFiles(root)) {
    const bytes = fs.readFileSync(file.absolute);
    if (bytes.includes(0)) continue;
    const text = bytes.toString("utf8");
    for (const rule of forbidden) assert.equal(rule.test(text), false, `C_env leakage '${rule}' in ${file.relative}`);
  }
}

function slugify(value) {
  return String(value).normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").replace(/-{2,}/g, "-");
}

function normalizedDescriptor(requirementGraph, stateNode) {
  return {
    requirement_id: requirementGraph.requirement_id,
    state_id: stateNode.state_id,
    key: slugify(requirementGraph.title),
    title: requirementGraph.title,
    family: requirementGraph.family_id,
    lifecycle: stateNode.lifecycle_status ?? "OBSERVED",
    components: stateNode.scope?.components ?? [],
    contexts: stateNode.scope?.contexts ?? [],
    attributes: stateNode.attributes ?? {},
    ambiguity: stateNode.ambiguity ?? null,
    execution: stateNode.execution ?? null,
    supporting_event_ids: stateNode.supporting_event_ids ?? [],
  };
}

function projected(stateNode) {
  return !new Set(["REMOVED", "DEFERRED"]).has(stateNode.lifecycle_status ?? "OBSERVED");
}

async function importFresh(modulePath, suffix) {
  return import(`${pathToFileURL(modulePath).href}?audit=${encodeURIComponent(suffix)}`);
}

function assertBalanced(text, label) {
  let depth = 0;
  let quoted = false;
  let escaped = false;
  for (const character of text) {
    if (quoted) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') quoted = false;
      continue;
    }
    if (character === '"') quoted = true;
    else if (character === "(") depth += 1;
    else if (character === ")") {
      depth -= 1;
      assert.ok(depth >= 0, `${label} closes before it opens`);
    }
  }
  assert.equal(quoted, false, `${label} ends inside a string`);
  assert.equal(depth, 0, `${label} is not balanced`);
}

function validateKicad(root, expectedStateMap) {
  const pcb = fs.readFileSync(path.join(root, "artifacts", "design.kicad_pcb"), "utf8");
  const sch = fs.readFileSync(path.join(root, "artifacts", "design.kicad_sch"), "utf8");
  const state = readJson(path.join(root, "artifacts", "design-state.json"));
  assert.ok(pcb.startsWith("(kicad_pcb "));
  assert.ok(sch.startsWith("(kicad_sch "));
  assert.match(pcb, /\(layer "Edge\.Cuts"\)/);
  assertBalanced(pcb, "PCB");
  assertBalanced(sch, "schematic");
  assert.deepEqual(state.state_map, expectedStateMap);
  return { pcb_root: true, schematic_root: true, balanced_s_expressions: true, edge_cuts: true, exact_design_state: true };
}

function stateMap(goldState) {
  return new Map(goldState.requirement_states.map((item) => [item.requirement_id, item.state_id]));
}

function applyTargetEvents(preMap, target, eventById) {
  const current = new Map(preMap);
  for (const eventId of target.task_event_ids) {
    const event = eventById.get(eventId);
    assert.ok(event, `Unknown event ${eventId}`);
    const observed = current.get(event.requirement_id);
    if (event.from_state_id === null) assert.equal(observed, undefined, `${eventId} expected no prior state`);
    else assert.equal(observed, event.from_state_id, `${eventId} transition source mismatch`);
    current.set(event.requirement_id, event.to_state_id);
  }
  return current;
}

function mapObject(map) {
  return Object.fromEntries([...map.entries()].sort(([a], [b]) => a.localeCompare(b, "en")));
}

function assertSemanticBoundaries(snapshots) {
  const t001 = snapshots.get(`${PROJECT_ID}_T001`);
  assert.ok(t001);
  assert.deepEqual(Object.keys(t001.stateMap).sort(), ["REQ_BATTERY_SAFETY_PROTECTION", "REQ_PCB_ARCHITECTURE_VARIANTS"]);
  assert.equal(t001.profile.batteryProtectionSpecified, true);
  assert.equal(t001.profile.overchargeCutoffSpecified, false);
  assert.equal(t001.features.some((item) => item.requirement_id === "REQ_BATTERY_CONNECTOR_INTERFACE"), false);

  const t002 = snapshots.get(`${PROJECT_ID}_T002`);
  assert.ok(t002);
  assert.equal(t002.stateMap.REQ_POWER_BOARD_MECHANICAL_FORM_FACTOR, "REQ_POWER_BOARD_MECHANICAL_FORM_FACTOR_S004");
  assert.equal(t002.profile.mountingHoleCount, 4);
  assert.equal(t002.profile.batteryNtcContact, true);
  assert.equal(t002.profile.batteryConnectorOrientation, "unspecified");

  const t016 = snapshots.get(`${PROJECT_ID}_T016`);
  assert.ok(t016);
  assert.equal(t016.stateMap.REQ_SEPARATE_BOARD_CONNECTOR_LAYOUT, "REQ_SEPARATE_BOARD_CONNECTOR_LAYOUT_S003");
  assert.equal(t016.profile.connectorTopAligned, true);
  assert.equal(t016.profile.lowerConnectorsUpward, false);

  const t017 = snapshots.get(`${PROJECT_ID}_T017`);
  assert.ok(t017);
  assert.equal(t017.stateMap.REQ_ESP32_FULL_PIN_BREAKOUT, "REQ_ESP32_FULL_PIN_BREAKOUT_S002");
  assert.equal(t017.profile.fullPinBreakout, true);
  assert.equal(t017.profile.throughHoleBreakout, true);
  assert.equal(t017.profile.openQuestions.some((item) => item.requirement_id === "REQ_ESP32_FULL_PIN_BREAKOUT"), false);
  assert.equal(t017.stateMap.REQ_BOM_ASSEMBLY_READINESS, "REQ_BOM_ASSEMBLY_READINESS_S007");
  assert.equal(t017.profile.bomStatus, "specified");
  assert.equal(t017.profile.diagnostics.some((item) => item.requirement_id === "REQ_BOM_ASSEMBLY_READINESS" && item.status === "FAILED"), false);

  const t026 = snapshots.get(`${PROJECT_ID}_T026`);
  assert.ok(t026);
  assert.equal(t026.stateMap.REQ_TOUCH_INPUT_INTERFACES, "REQ_TOUCH_INPUT_INTERFACES_S002");
  assert.equal(t026.profile.touchInputCount, 2);
  assert.equal(t026.profile.pirInputPresent, true);
  assert.equal(t026.profile.panelInputCount, 3);
  assert.equal(t026.profile.inputBiasSpecified, false);
  assert.equal(t026.profile.vrtcHandling, "specified");
  assert.equal(t026.profile.vbackupAccess, true);
  assert.equal(t026.profile.vbackupLocationSpecified, false);
}

const graph = readJson(GRAPH_PATH);
const gold = readJson(GOLD_PATH);
const normalized = readJson(NORMALIZED_PATH);
assert.equal(String(graph.project_id), PROJECT_ID);
assert.equal(String(gold.project_id), PROJECT_ID);
assert.equal(String(normalized.project_id), PROJECT_ID);
const messageOrder = new Map(normalized.messages.map((message, index) => [message.message_id, index]));
const graphByRequirement = new Map(graph.requirement_graphs.map((item) => [item.requirement_id, item]));
const stateById = new Map(graph.requirement_graphs.flatMap((requirementGraph) => requirementGraph.nodes.map((stateNode) => [stateNode.state_id, { requirementGraph, stateNode }])));
const eventById = new Map(graph.requirement_graphs.flatMap((requirementGraph) => requirementGraph.edges.map((event) => [event.event_id, { ...event, requirement_id: requirementGraph.requirement_id }])));
const goldById = new Map(gold.task_gold_states.map((item) => [item.target_id, item]));
const targetIndex = readJson(path.join(REPORTS_ROOT, "target_index.json"));
const validation = readJson(path.join(REPORTS_ROOT, "validation_report.json"));
assert.equal(validation.overall, "PASS");
assert.deepEqual(new Set(targetIndex.map((item) => item.target_id)), new Set(goldById.keys()));

assert.equal(path.dirname(TEMP_ROOT), PACKAGE_ROOT);
fs.rmSync(TEMP_ROOT, { recursive: true, force: true });
fs.mkdirSync(TEMP_ROOT, { recursive: true });

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const targetSummaries = [];
const snapshots = new Map();
const finalDeliveredHashes = new Set(listFiles(FINAL_DELIVERABLE_ROOT).map((item) => crypto.createHash("sha256").update(fs.readFileSync(item.absolute)).digest("hex")));

try {
  const targetDirectories = fs.readdirSync(TARGETS_ROOT, { withFileTypes: true }).filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort();
  const expectedDirectories = gold.task_gold_states.map((target) => `${target.target_id.replace(`${PROJECT_ID}_`, "")}_before_${target.target_task.source_message_id}`).sort();
  assert.deepEqual(targetDirectories, expectedDirectories);
  for (const directoryName of targetDirectories) {
    const targetRoot = path.join(TARGETS_ROOT, directoryName);
    const manifest = readJson(path.join(targetRoot, "manifest.json"));
    const target = goldById.get(manifest.target_id);
    assert.ok(target, `Unexpected target ${manifest.target_id}`);
    assert.equal(manifest.before_message_id, target.target_task.source_message_id);
    assert.deepEqual(manifest.target_event_ids, target.task_event_ids);
    assert.deepEqual(manifest.target_event_types, target.task_event_ids.map((eventId) => eventById.get(eventId).event_type));
    assert.equal(manifest.rq4_eligible, target.primary_rq_targets.includes("RQ4"));
    assert.equal(manifest.pre_state_verified_against_gold, true);
    assert.equal(manifest.post_state_verified_against_gold, true);

    const expectedState = stateMap(target.pre_task_gold_state);
    const mappedState = new Map(manifest.requirements_to_code.map((item) => [item.requirement_id, item.state_id]));
    assert.deepEqual(mapObject(mappedState), mapObject(expectedState));
    const replayedPost = applyTargetEvents(expectedState, target, eventById);
    assert.deepEqual(mapObject(replayedPost), mapObject(stateMap(target.post_task_gold_state)));

    const cutoff = messageOrder.get(manifest.before_message_id);
    for (const stateId of expectedState.values()) {
      const stateNode = stateById.get(stateId).stateNode;
      for (const eventId of stateNode.supporting_event_ids) assert.ok(messageOrder.get(eventById.get(eventId).source_message_id) < cutoff, `${manifest.target_id} future event leakage: ${eventId}`);
    }

    const expandedRoot = path.join(targetRoot, "pre_repo");
    assert.equal(treeHash(expandedRoot), manifest.repo_sha256);
    assertNoSecrets(expandedRoot);
    for (const file of listFiles(expandedRoot)) {
      const hash = crypto.createHash("sha256").update(fs.readFileSync(file.absolute)).digest("hex");
      assert.equal(finalDeliveredHashes.has(hash), false, `Final deliverable content leaked into ${manifest.target_id}: ${file.relative}`);
    }
    const extractedRoot = path.join(TEMP_ROOT, manifest.target_id);
    extractArchive(path.join(targetRoot, "pre_repo.zip"), extractedRoot);
    assert.equal(treeHash(extractedRoot), manifest.repo_sha256);
    run(npm, ["ci", "--ignore-scripts"], extractedRoot);
    run(npm, ["run", "check"], extractedRoot);

    const runtime = await importFresh(path.join(extractedRoot, "src", "snapshot.mjs"), manifest.target_id);
    const expectedRuntimeState = new Map([...expectedState].filter(([, stateId]) => projected(stateById.get(stateId).stateNode)));
    assert.deepEqual(runtime.snapshot.stateMap, mapObject(expectedRuntimeState));
    let projectedCount = 0;
    for (const mapping of manifest.requirements_to_code) {
      const indexed = stateById.get(mapping.state_id);
      assert.ok(indexed);
      assert.equal(indexed.requirementGraph.requirement_id, mapping.requirement_id);
      if (!projected(indexed.stateNode)) {
        assert.deepEqual(mapping.code_paths, []);
        continue;
      }
      projectedCount += 1;
      const modulePath = path.join(extractedRoot, "src", "features", `${slugify(indexed.requirementGraph.title)}.mjs`);
      assert.ok(fs.existsSync(modulePath));
      const actual = (await importFresh(modulePath, `${manifest.target_id}-${mapping.requirement_id}`)).default;
      const { render_hints: ignoredHints, ...actualCanonical } = JSON.parse(JSON.stringify(actual));
      assert.deepEqual(actualCanonical, normalizedDescriptor(indexed.requirementGraph, indexed.stateNode));
    }
    assert.equal(projectedCount, manifest.active_code_feature_count);
    assert.equal(runtime.snapshot.features.length, projectedCount);
    const kicadAudit = validateKicad(extractedRoot, mapObject(expectedRuntimeState));
    snapshots.set(manifest.target_id, JSON.parse(JSON.stringify({ ...runtime.snapshot, profile: runtime.profile })));
    targetSummaries.push({ target_id: manifest.target_id, before_message_id: manifest.before_message_id, rq4_eligible: manifest.rq4_eligible, exact_gold_state_map: true, future_event_exclusion: true, graph_descriptor_projection: true, clean_install_build_and_tests: "PASS", kicad: kicadAudit, archive_expanded_tree_equivalence: true });
  }
  assertSemanticBoundaries(snapshots);

  const cenvExtracted = path.join(TEMP_ROOT, "cenv");
  extractArchive(CENV_ARCHIVE, cenvExtracted);
  const cenvRoot = path.join(cenvExtracted, `${PROJECT_ID}_C_env_complete`);
  const cenvProject = path.join(cenvRoot, "project");
  const cenvManifest = readJson(path.join(cenvRoot, "reconstruction_audit", "cenv_manifest.json"));
  assert.equal(treeHash(cenvProject), cenvManifest.project_sha256);
  assertNoSecrets(cenvProject);
  assertZeroDomain(cenvProject);
  for (const file of listFiles(cenvProject)) {
    const hash = crypto.createHash("sha256").update(fs.readFileSync(file.absolute)).digest("hex");
    assert.equal(finalDeliveredHashes.has(hash), false, `Final deliverable content leaked into C_env: ${file.relative}`);
  }
  run(npm, ["ci", "--ignore-scripts"], cenvProject);
  run(npm, ["run", "check"], cenvProject);
  const cenvRuntime = await importFresh(path.join(cenvProject, "src", "snapshot.mjs"), "cenv");
  assert.deepEqual(cenvRuntime.snapshot.features, []);
  assert.deepEqual(cenvRuntime.snapshot.stateMap, {});
  const cenvKicad = validateKicad(cenvProject, {});

  const report = {
    schema_version: "1.0",
    project_id: PROJECT_ID,
    overall: "PASS",
    independence: "This auditor reads generated artifacts and canonical Graph/Gold inputs; it does not import the reconstruction generator or its helper modules.",
    c_env: { archive_extractable: true, archive_paths_safe: true, project_tree_hash_matches_manifest: true, zero_domain_feature_count: 0, zero_domain_leakage_scan: "PASS", secret_and_pii_scan: "PASS", clean_install_build_and_tests: "PASS", kicad: cenvKicad },
    targets: targetSummaries,
    exact_gold_target_set: true,
    exact_gold_pre_state_maps: true,
    exact_gold_post_replay: true,
    exact_gold_event_ids_types_and_order: true,
    supporting_events_strictly_before_cutoff: true,
    final_deliverable_content_absent_from_all_pre_repos: true,
    semantic_boundary_assertions: "PASS",
    rq4_target_ids: gold.task_gold_states.filter((item) => item.primary_rq_targets.includes("RQ4")).map((item) => item.target_id),
  };
  writeJson(path.join(REPORTS_ROOT, "independent_audit_report.json"), report);
  process.stdout.write(`PASS: independent audit verified C_env and ${targetSummaries.length} target archives for ${PROJECT_ID}.\n`);
} finally {
  fs.rmSync(TEMP_ROOT, { recursive: true, force: true });
}
