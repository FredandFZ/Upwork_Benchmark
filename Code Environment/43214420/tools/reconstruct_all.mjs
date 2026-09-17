#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  createDeterministicZip,
  invariant,
  jsonText,
  listFiles,
  readJson,
  resetOwnedDirectory,
  runCommand,
  scanTextFiles,
  sha256File,
  sha256Tree,
  toPosix,
  validateZip,
  writeJson,
  writeText,
} from "./lib/archive.mjs";
import { createKicadRepository, featureDescriptor, isProjected, slugify } from "./lib/kicad_repository.mjs";

const PROJECT_ID = "43214420";
const SCHEMA_VERSION = "2.0";
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = path.resolve(SCRIPT_DIR, "..");
const WORKSPACE_ROOT = path.resolve(PACKAGE_ROOT, "..", "..");
const TEMPLATE_ROOT = path.join(SCRIPT_DIR, "templates", "kicad-repo");

const DELIVERABLE_ROOT = path.join(WORKSPACE_ROOT, "Datasets", "PII_clean_project", PROJECT_ID, "deliverables", "paid_18156583", "IoT_Environmental_Monitoring_Device_Power");
const INPUTS = Object.freeze({
  requirement_graph: path.join(WORKSPACE_ROOT, "outputs", "stage2", PROJECT_ID, "requirement_state_graph.json"),
  gold_states: path.join(WORKSPACE_ROOT, "outputs", "stage2", PROJECT_ID, "gold_states.json"),
  normalized_project: path.join(WORKSPACE_ROOT, "outputs", "stage1_runs", PROJECT_ID, "normalized_project.json"),
  stage1_annotation: path.join(WORKSPACE_ROOT, "outputs", "stage1_annotations", `${PROJECT_ID}_stage1_annotation.json`),
  pii_clean_chat: path.join(WORKSPACE_ROOT, "Datasets", "PII_clean_project", PROJECT_ID, "chat_messages.json"),
  pii_clean_job: path.join(WORKSPACE_ROOT, "Datasets", "PII_clean_project", PROJECT_ID, "job.txt"),
  pii_clean_milestones: path.join(WORKSPACE_ROOT, "Datasets", "PII_clean_project", PROJECT_ID, "milestones.json"),
  pii_clean_job_metadata: path.join(WORKSPACE_ROOT, "Datasets", "PII_clean_project", PROJECT_ID, "job_metadata.csv"),
});
const OUTPUTS = Object.freeze({
  cenv: path.join(PACKAGE_ROOT, "C_env"),
  reports: path.join(PACKAGE_ROOT, "reports"),
  targets: path.join(PACKAGE_ROOT, "targets"),
});

const SECRET_PATTERNS = Object.freeze([
  { name: "private-key", regex: /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/i },
  { name: "aws-access-key", regex: /AKIA[0-9A-Z]{16}/ },
  { name: "github-token", regex: /gh[pousr]_[A-Za-z0-9]{30,}/ },
  { name: "slack-token", regex: /xox[baprs]-[A-Za-z0-9-]{20,}/ },
  { name: "openai-key", regex: /sk-[A-Za-z0-9_-]{32,}/ },
  { name: "email-address", regex: /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i },
  { name: "credential-assignment", regex: /(?:password|passwd|pwd)\s*[:=]\s*(?!placeholder|example|not-set)[^\s]{6,}/i },
  { name: "redacted-sensitive-token", regex: /\[(?:PASSWORD|ACCOUNT|EMAIL)_\d+\]/i },
]);

const CENV_FORBIDDEN_PATTERNS = Object.freeze([
  { name: "future-domain-term:IoT", regex: /\bIoT\b/i },
  { name: "future-domain-term:ESP32", regex: /\bESP32(?:-S3)?\b/i },
  { name: "future-domain-term:AXP2101", regex: /\bAXP2101\b/i },
  { name: "future-domain-term:TTP223", regex: /\bTTP223\b/i },
  { name: "future-domain-term:SPS30", regex: /\bSPS30\b/i },
  { name: "future-domain-term:SK6812", regex: /\bSK6812/i },
  { name: "future-domain-term:JLCPCB", regex: /\bJLCPCB\b/i },
]);

function copyStateMap(value) {
  return new Map(value.entries());
}

function stateMapFromGold(goldState) {
  return new Map(goldState.requirement_states.map((item) => [item.requirement_id, item.state_id]));
}

function sortedStateObject(stateMap) {
  return Object.fromEntries([...stateMap.entries()].sort(([a], [b]) => a.localeCompare(b, "en")));
}

function assertSameStateMap(actual, expected, context) {
  invariant(JSON.stringify(sortedStateObject(actual)) === JSON.stringify(sortedStateObject(expected)), `${context} state mismatch`);
}

function sourceChecksums() {
  const artifacts = {};
  for (const [name, filePath] of Object.entries(INPUTS)) {
    invariant(fs.existsSync(filePath), `Missing source artifact: ${filePath}`);
    artifacts[name] = { path: toPosix(path.relative(WORKSPACE_ROOT, filePath)), sha256: sha256File(filePath), bytes: fs.statSync(filePath).size };
  }
  invariant(fs.existsSync(DELIVERABLE_ROOT), `Missing final deliverable tree: ${DELIVERABLE_ROOT}`);
  const finalFiles = listFiles(DELIVERABLE_ROOT);
  invariant(finalFiles.length >= 50, `Expected a populated final KiCad deliverable tree, found ${finalFiles.length} files`);
  artifacts.final_deliverable_tree = {
    path: toPosix(path.relative(WORKSPACE_ROOT, DELIVERABLE_ROOT)),
    sha256: sha256Tree(DELIVERABLE_ROOT),
    bytes: finalFiles.reduce((total, item) => total + fs.statSync(item.absolute).size, 0),
    file_count: finalFiles.length,
    temporal_use: "checksum-only-final-evidence-not-copied-to-pre-state",
  };
  const criticalFinalFiles = finalFiles.filter((item) => /\.(?:kicad_pcb|kicad_sch|kicad_pro)$/i.test(item.relative));
  invariant(criticalFinalFiles.length === 3, `Expected three primary final KiCad files, found ${criticalFinalFiles.length}`);
  for (const item of criticalFinalFiles) artifacts[`final_${slugify(item.relative)}`] = {
    path: toPosix(path.relative(WORKSPACE_ROOT, item.absolute)),
    sha256: sha256File(item.absolute),
    bytes: fs.statSync(item.absolute).size,
    temporal_use: "checksum-only-final-evidence-not-copied-to-pre-state",
  };
  return artifacts;
}

function buildIndexes(requirementData, normalizedProject) {
  const messageOrder = new Map(normalizedProject.messages.map((message, index) => [message.message_id, index]));
  const graphByRequirement = new Map();
  const stateById = new Map();
  const eventById = new Map();
  const events = [];
  requirementData.requirement_graphs.forEach((requirementGraph, graphIndex) => {
    invariant(!graphByRequirement.has(requirementGraph.requirement_id), `Duplicate requirement: ${requirementGraph.requirement_id}`);
    graphByRequirement.set(requirementGraph.requirement_id, requirementGraph);
    for (const stateNode of requirementGraph.nodes) {
      invariant(!stateById.has(stateNode.state_id), `Duplicate state: ${stateNode.state_id}`);
      stateById.set(stateNode.state_id, { requirementGraph, stateNode });
    }
    requirementGraph.edges.forEach((edge, edgeIndex) => {
      invariant(messageOrder.has(edge.source_message_id), `Unknown source message for ${edge.event_id}`);
      invariant(!eventById.has(edge.event_id), `Duplicate event: ${edge.event_id}`);
      const record = { ...edge, requirement_id: requirementGraph.requirement_id, graph_index: graphIndex, edge_index: edgeIndex };
      eventById.set(edge.event_id, record);
      events.push(record);
    });
  });
  events.sort((a, b) => messageOrder.get(a.source_message_id) - messageOrder.get(b.source_message_id) || a.graph_index - b.graph_index || a.edge_index - b.edge_index);
  return { messageOrder, graphByRequirement, stateById, eventById, events };
}

function replayTimeline(goldData, indexes) {
  const targetByMessage = new Map();
  for (const target of goldData.task_gold_states) {
    const messageId = target.target_task.source_message_id;
    invariant(!targetByMessage.has(messageId), `Duplicate target boundary ${messageId}`);
    targetByMessage.set(messageId, target);
    for (const eventId of target.task_event_ids) {
      const event = indexes.eventById.get(eventId);
      invariant(event?.source_message_id === messageId, `Target event ${eventId} has wrong source message`);
    }
  }

  const groups = [];
  for (const event of indexes.events) {
    if (groups.at(-1)?.message_id !== event.source_message_id) groups.push({ message_id: event.source_message_id, events: [] });
    groups.at(-1).events.push(event);
  }

  const current = new Map();
  const targetSnapshots = new Map();
  const ledger = [];
  for (const group of groups) {
    const target = targetByMessage.get(group.message_id) ?? null;
    const before = copyStateMap(current);
    if (target) {
      assertSameStateMap(before, stateMapFromGold(target.pre_task_gold_state), `${target.target_id} pre-task`);
      targetSnapshots.set(target.target_id, before);
    }
    let orderedEvents = group.events;
    if (target) {
      const groupedIds = new Set(group.events.map((event) => event.event_id));
      invariant(target.task_event_ids.length === groupedIds.size && target.task_event_ids.every((eventId) => groupedIds.has(eventId)), `${target.target_id} task event set differs from graph message group`);
      orderedEvents = target.task_event_ids.map((eventId) => indexes.eventById.get(eventId));
    }
    for (const event of orderedEvents) {
      const observed = current.get(event.requirement_id);
      if (event.from_state_id === null) invariant(observed === undefined, `${event.event_id} expected no prior state`);
      else invariant(observed === event.from_state_id, `${event.event_id} expected ${event.from_state_id}, found ${observed}`);
      invariant(indexes.stateById.get(event.to_state_id)?.requirementGraph.requirement_id === event.requirement_id, `${event.event_id} points to invalid state`);
      current.set(event.requirement_id, event.to_state_id);
    }
    const after = copyStateMap(current);
    if (target) assertSameStateMap(after, stateMapFromGold(target.post_task_gold_state), `${target.target_id} post-task`);
    ledger.push({
      message_id: group.message_id,
      atomic: true,
      target_id: target?.target_id ?? null,
      events: orderedEvents.map((event) => ({ event_id: event.event_id, event_type: event.event_type, requirement_id: event.requirement_id, from_state_id: event.from_state_id, to_state_id: event.to_state_id })),
      state_count_before: before.size,
      state_count_after: after.size,
      gold_pre_verified: Boolean(target),
      gold_post_verified: Boolean(target),
    });
  }
  invariant(targetSnapshots.size === goldData.task_gold_states.length, "Not every Gold target was reconstructed");
  return { targetSnapshots, ledger };
}

function materializeFeatures(stateMap, indexes) {
  const features = [];
  for (const requirementGraph of indexes.graphByRequirement.values()) {
    const stateId = stateMap.get(requirementGraph.requirement_id);
    if (!stateId) continue;
    const indexed = indexes.stateById.get(stateId);
    invariant(indexed?.requirementGraph.requirement_id === requirementGraph.requirement_id, `Wrong requirement for ${stateId}`);
    if (!isProjected(indexed.stateNode)) continue;
    features.push(featureDescriptor(requirementGraph, indexed.stateNode));
  }
  return features.sort((a, b) => a.key.localeCompare(b.key, "en"));
}

function requirementMappings(stateMap, indexes) {
  const mappings = [];
  for (const requirementGraph of indexes.graphByRequirement.values()) {
    const stateId = stateMap.get(requirementGraph.requirement_id);
    if (!stateId) continue;
    const stateNode = indexes.stateById.get(stateId).stateNode;
    const projected = isProjected(stateNode);
    const key = slugify(requirementGraph.title);
    mappings.push({
      requirement_id: requirementGraph.requirement_id,
      state_id: stateId,
      lifecycle: stateNode.lifecycle_status ?? "OBSERVED",
      components: stateNode.scope?.components ?? [],
      implementation_mode: projected ? "synthetic-kicad-executable" : "excluded-lifecycle",
      code_paths: projected ? [`src/features/${key}.mjs`, "src/snapshot.mjs", "src/operations.mjs", "src/design.mjs", "artifacts/design.kicad_pcb", "artifacts/design.kicad_sch", "artifacts/design-state.json"] : [],
    });
  }
  return mappings;
}

function validateSExpression(text, label) {
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
      invariant(depth >= 0, `${label} closes before it opens`);
    }
  }
  invariant(!quoted && depth === 0, `${label} is not balanced`);
}

function validateKicadArtifacts(repositoryRoot) {
  const pcbPath = path.join(repositoryRoot, "artifacts", "design.kicad_pcb");
  const schPath = path.join(repositoryRoot, "artifacts", "design.kicad_sch");
  const statePath = path.join(repositoryRoot, "artifacts", "design-state.json");
  const pcb = fs.readFileSync(pcbPath, "utf8");
  const sch = fs.readFileSync(schPath, "utf8");
  invariant(pcb.startsWith("(kicad_pcb "), "Generated PCB has the wrong root");
  invariant(sch.startsWith("(kicad_sch "), "Generated schematic has the wrong root");
  invariant(/\(layer "Edge\.Cuts"\)/.test(pcb), "Generated PCB lacks an Edge.Cuts outline");
  validateSExpression(pcb, "PCB");
  validateSExpression(sch, "schematic");
  const state = readJson(statePath);
  invariant(state && typeof state.state_map === "object" && state.profile, "Generated design-state artifact is incomplete");
  return {
    status: "PASS",
    pcb: { syntax: "balanced", edge_cuts: true, bytes: fs.statSync(pcbPath).size, sha256: sha256File(pcbPath) },
    schematic: { syntax: "balanced", bytes: fs.statSync(schPath).size, sha256: sha256File(schPath) },
    design_state: { parsed: true, state_count: Object.keys(state.state_map).length, bytes: fs.statSync(statePath).size, sha256: sha256File(statePath) },
  };
}

function validateRunnableRepository(repositoryRoot) {
  const npm = process.platform === "win32" ? "npm.cmd" : "npm";
  const commands = [runCommand(repositoryRoot, npm, ["ci", "--ignore-scripts"]), runCommand(repositoryRoot, npm, ["run", "check"])];
  const kicad = validateKicadArtifacts(repositoryRoot);
  fs.rmSync(path.join(repositoryRoot, "node_modules"), { recursive: true, force: true });
  return { status: "PASS", commands, kicad };
}

function assertTemporalSnapshot(target, stateMap, indexes) {
  const cutoffOrder = indexes.messageOrder.get(target.target_task.source_message_id);
  invariant(cutoffOrder !== undefined, `Missing target message ${target.target_task.source_message_id}`);
  assertSameStateMap(stateMap, stateMapFromGold(target.pre_task_gold_state), `${target.target_id} temporal oracle`);
  for (const [requirementId, stateId] of stateMap) {
    const stateNode = indexes.stateById.get(stateId)?.stateNode;
    invariant(stateNode, `Unknown state ${stateId}`);
    invariant(stateNode.supporting_event_ids.every((eventId) => indexes.messageOrder.get(indexes.eventById.get(eventId).source_message_id) < cutoffOrder), `${target.target_id} leaks event at or after cutoff through ${requirementId}`);
  }
}

function createCenv(checksums) {
  const bundleName = `${PROJECT_ID}_C_env_complete`;
  const stageRoot = path.join(OUTPUTS.cenv, bundleName);
  const projectRoot = path.join(stageRoot, "project");
  const auditRoot = path.join(stageRoot, "reconstruction_audit");
  createKicadRepository(projectRoot, TEMPLATE_ROOT, {
    features: [],
    environmentLabel: "completed-zero-domain-baseline",
    repositoryLabel: `${PROJECT_ID} Completed Zero-Domain PCB Environment`,
  });
  const runtimeValidation = validateRunnableRepository(projectRoot);
  const leakageFindings = scanTextFiles(projectRoot, CENV_FORBIDDEN_PATTERNS);
  const secretFindings = scanTextFiles(projectRoot, SECRET_PATTERNS);
  invariant(leakageFindings.length === 0, `C_env future leakage: ${JSON.stringify(leakageFindings)}`);
  invariant(secretFindings.length === 0, `C_env secret/PII findings: ${JSON.stringify(secretFindings)}`);
  const projectSha = sha256Tree(projectRoot);
  writeJson(path.join(auditRoot, "artifact_decisions.json"), {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    historical_source_status: "final-deliverables-present-but-no-proven-pre-target-version",
    chosen_executable_substrate: "dependency-free Node.js KiCad-fixture generator and PCB behavior harness",
    final_artifact_policy: "The final KiCad, production, library, 3D, and BOM tree is checksummed as external evidence only and never copied into a pre-event repository.",
    boundary_policy: "The completed C_env contains the generic runnable scaffold and zero project-specific requirement modules.",
    native_validation_policy: "Generated KiCad-compatible s-expressions receive independent root, balance, and Edge.Cuts checks. kicad-cli is unavailable, so no native ERC/DRC claim is made.",
  });
  writeJson(path.join(auditRoot, "cenv_manifest.json"), {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    baseline_type: "synthetic-kicad-compatible",
    repository_classification: "completed-zero-domain-baseline",
    project_sha256: projectSha,
    source_artifact_checksums: checksums,
    toolchain: { executable_reconstruction: [process.version, "npm lockfile v3", "Node.js standard library only", "KiCad-compatible board/schematic s-expressions", "exact JSON design-state artifact"] },
    commands: ["npm ci --ignore-scripts", "npm run check", "npm run inspect"],
    limitations: [
      "The final delivered KiCad tree does not establish availability at any selected pre-event boundary.",
      "The synthetic PCB/schematic fixtures are behavior-bearing temporal reconstructions, not byte-identical historical boards.",
      "kicad-cli is unavailable in the current workspace; native KiCad ERC/DRC is not claimed.",
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
  return { archivePath, projectSha, runtimeValidation, archiveValidation };
}

function createTarget(target, stateMap, indexes) {
  assertTemporalSnapshot(target, stateMap, indexes);
  const messageId = target.target_task.source_message_id;
  const shortId = target.target_id.replace(`${PROJECT_ID}_`, "");
  const targetRoot = path.join(OUTPUTS.targets, `${shortId}_before_${messageId}`);
  const repositoryRoot = path.join(targetRoot, "pre_repo");
  const features = materializeFeatures(stateMap, indexes);
  createKicadRepository(repositoryRoot, TEMPLATE_ROOT, {
    features,
    environmentLabel: "reconstructed-pre-event",
    repositoryLabel: `${PROJECT_ID} ${shortId} Reconstructed PCB Pre-Event Repository`,
  });
  const runtimeValidation = validateRunnableRepository(repositoryRoot);
  const secretFindings = scanTextFiles(repositoryRoot, SECRET_PATTERNS);
  invariant(secretFindings.length === 0, `${target.target_id} secret/PII findings: ${JSON.stringify(secretFindings)}`);
  const repoSha = sha256Tree(repositoryRoot);
  const archivePath = path.join(targetRoot, "pre_repo.zip");
  createDeterministicZip(repositoryRoot, archivePath);
  const archiveValidation = validateZip(archivePath);
  const targetEvents = target.task_event_ids.map((eventId) => indexes.eventById.get(eventId));
  invariant(targetEvents.every(Boolean), `${target.target_id} references an unknown event`);
  const targetEventTypes = targetEvents.map((event) => event.event_type);
  const rq4Eligible = target.primary_rq_targets.includes("RQ4");
  const manifest = {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    target_id: target.target_id,
    before_message_id: messageId,
    repository_classification: "synthetic-kicad-executable-pre-state",
    contract_layer: "graph-backed-requirement-modules-plus-kicad-compatible-fixtures-and-behavior-model",
    active_code_feature_count: features.length,
    tracked_requirement_count: stateMap.size,
    temporal_fixture: null,
    source_artifact_temporal_policy: "final KiCad/production deliverable tree is checksum-only; never copied into pre_repo",
    primary_rq_targets: [...target.primary_rq_targets],
    rq4_eligible: rq4Eligible,
    target_actionability: rq4Eligible ? "rq4-executable-pcb-design-change" : "state-transition-not-selected-for-rq4",
    requirements_to_code: requirementMappings(stateMap, indexes),
    target_event_ids: [...target.task_event_ids],
    target_event_types: targetEventTypes,
    pre_state_verified_against_gold: true,
    post_state_verified_against_gold: true,
    no_events_at_or_after_boundary_in_pre_state: true,
    generated_kicad: runtimeValidation.kicad,
    repo_sha256: repoSha,
  };
  writeJson(path.join(targetRoot, "manifest.json"), manifest);
  return { manifest, repositoryRoot, runtimeValidation, archiveValidation, secretScan: { status: "PASS", finding_count: 0 } };
}

function writeReports(requirementData, goldData, checksums, replay, cenv, targets, indexes) {
  const rq4Ids = targets.filter((item) => item.manifest.rq4_eligible).map((item) => item.manifest.target_id);
  writeJson(path.join(OUTPUTS.reports, "source_checksums.json"), { schema_version: SCHEMA_VERSION, project_id: PROJECT_ID, artifacts: checksums });
  writeJson(path.join(OUTPUTS.reports, "artifact_evidence.json"), {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    final_tree_file_count: checksums.final_deliverable_tree.file_count,
    final_tree_bytes: checksums.final_deliverable_tree.bytes,
    primary_kicad_file_count: Object.keys(checksums).filter((key) => key.startsWith("final_") && key !== "final_deliverable_tree").length,
    temporal_decision: "The final KiCad/production deliverable tree is checksum evidence only; no file from it is copied into C_env or a target pre-state.",
    evidence_gap: "No version-controlled or timestamp-proven pre-target KiCad source snapshot is present in the local corpus.",
  });
  writeJson(path.join(OUTPUTS.reports, "replay_manifest.json"), {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    replay_policy: "Events sharing a source message are applied atomically; selected target groups use exact Gold task_event_ids order.",
    requirement_count: requirementData.requirement_graphs.length,
    event_count: indexes.events.length,
    target_count: goldData.task_gold_states.length,
    all_target_pre_states_verified: true,
    all_target_post_states_verified: true,
    ledger: replay.ledger,
  });
  writeJson(path.join(OUTPUTS.reports, "target_index.json"), targets.map((item) => item.manifest));
  writeJson(path.join(OUTPUTS.reports, "validation_report.json"), {
    schema_version: SCHEMA_VERSION,
    project_id: PROJECT_ID,
    overall: "PASS",
    reconstruction_classification: "synthetic-kicad-executable",
    c_env: { status: "PASS", project_sha256: cenv.projectSha, runtime_validation: cenv.runtimeValidation, archive_validation: cenv.archiveValidation, zero_domain_leakage_scan: "PASS", secret_and_pii_scan: "PASS" },
    replay: { status: "PASS", event_group_count: replay.ledger.length, target_count: targets.length, pre_state_gold_matches: targets.length, post_state_gold_matches: targets.length },
    targets: targets.map((item) => ({ target_id: item.manifest.target_id, before_message_id: item.manifest.before_message_id, status: "PASS", repo_sha256: item.manifest.repo_sha256, runtime_validation: item.runtimeValidation, archive_validation: item.archiveValidation, secret_and_pii_scan: item.secretScan })),
    loader_contract: { status: "PASS", exact_target_set: true, exact_gold_pre_and_post_maps: true, event_ids_types_and_order_match_gold: true, cutoff_supporting_events_strictly_earlier: true, all_archives_safe_and_crc_verified: true },
    native_kicad_gate: { status: "NOT_RUN_NO_KICAD_CLI", note: "kicad-cli is unavailable; independent s-expression, Edge.Cuts, deterministic-build, and behavior checks remain PASS." },
  });
  writeText(path.join(OUTPUTS.reports, "reconstruction_report.md"), `# ${PROJECT_ID} reconstruction report\n\n## Outcome\n\nThe package contains one completed zero-domain PCB environment and ${targets.length} independently runnable pre-event repositories. Atomic replay matches every Gold pre-state and post-state. The RQ4 targets are ${rq4Ids.join(", ")}.\n\nEach repository builds deterministic KiCad-compatible board/schematic fixtures and an exact JSON design-state artifact. Behavior operations expose mechanical envelope, connector layout, pin breakout, power safety, input interfaces, and manufacturing status. The harness uses only the Node.js standard library and needs no network service, credential, or KiCad installation for build and tests.\n\n## Fidelity boundary\n\nThe final deliverable tree contains ${checksums.final_deliverable_tree.file_count} files, including primary KiCad sources, production exports, libraries, 3D models, and a BOM. Its dataset placement does not establish availability at earlier boundaries, so it is checksummed only and never copied into C_env or a pre_repo. Generated fixtures are synthetic executable state projections, not claimed historical boards.\n\nThe graph contains ${requirementData.requirement_graphs.length} requirements and ${indexes.events.length} events across ${targets.length} target boundaries. RQ4 covers battery protection/connector introduction (T001), mechanical and battery-access refinement (T002), separate-board connector placement (T016), the unresolved full-pin-breakout question plus BOM failure transition (T017), and the multi-requirement input/power-access change group (T026).\n\n## Verification\n\n- Clean install, syntax, deterministic build, tests: PASS\n- KiCad root, balanced s-expression, and Edge.Cuts checks: PASS\n- Exact design-state artifact comparison: PASS\n- Gold pre-state and post-state comparisons: ${targets.length}/${targets.length} PASS\n- Strict before-message future-event exclusion: PASS\n- C_env zero-domain leakage and secret/PII scans: PASS\n- ZIP safe path, CRC, no symlink, no .git: PASS\n- Native kicad-cli ERC/DRC: not run because kicad-cli is unavailable\n`);
  writeText(path.join(PACKAGE_ROOT, "README.md"), `# ${PROJECT_ID} Reconstruction Package\n\nStart with \`reports/reconstruction_report.md\`.\n\n- \`C_env/${PROJECT_ID}_C_env_complete.zip\`: completed zero-domain executable PCB baseline.\n- \`targets/Txxx_before_<message>/pre_repo.zip\`: runnable pre-event repository.\n- \`targets/.../manifest.json\`: exact state-to-code and temporal-boundary mapping.\n- \`reports/replay_manifest.json\`: complete atomic event replay ledger.\n- \`reports/validation_report.json\`: build, artifact, leakage, archive, and credential checks.\n- \`tools/reconstruct_all.mjs\`: deterministic generator.\n- \`tools/audit_outputs.mjs\`: independent Gold/archive/behavior audit.\n`);
}

for (const directory of Object.values(OUTPUTS)) resetOwnedDirectory(directory, PACKAGE_ROOT, Object.values(OUTPUTS));
const checksums = sourceChecksums();
const requirementData = readJson(INPUTS.requirement_graph);
const goldData = readJson(INPUTS.gold_states);
const normalizedProject = readJson(INPUTS.normalized_project);
invariant(String(requirementData.project_id) === PROJECT_ID, "Requirement graph project ID mismatch");
invariant(String(goldData.project_id) === PROJECT_ID, "Gold state project ID mismatch");
invariant(String(normalizedProject.project_id) === PROJECT_ID, "Normalized project ID mismatch");
const indexes = buildIndexes(requirementData, normalizedProject);
const replay = replayTimeline(goldData, indexes);
const cenv = createCenv(checksums);
const targets = [];
for (const target of goldData.task_gold_states) {
  process.stdout.write(`Reconstructing ${target.target_id} before message ${target.target_task.source_message_id}...\n`);
  targets.push(createTarget(target, replay.targetSnapshots.get(target.target_id), indexes));
}
writeReports(requirementData, goldData, checksums, replay, cenv, targets, indexes);
process.stdout.write(`PASS: reconstructed ${PROJECT_ID} C_env and ${targets.length} pre-event repositories.\n`);
