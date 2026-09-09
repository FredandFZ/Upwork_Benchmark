#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const PROJECT_ID = "43772711";
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = path.resolve(SCRIPT_DIR, "..");
const WORKSPACE_ROOT = path.resolve(PACKAGE_ROOT, "..", "..");
const GRAPH_PATH = path.join(WORKSPACE_ROOT, "outputs", "stage2", PROJECT_ID, "requirement_state_graph.json");
const GOLD_PATH = path.join(WORKSPACE_ROOT, "outputs", "stage2", PROJECT_ID, "gold_states.json");
const CENV_ARCHIVE = path.join(PACKAGE_ROOT, "C_env", `${PROJECT_ID}_C_env_complete.zip`);
const TARGETS_ROOT = path.join(PACKAGE_ROOT, "targets");
const REPORTS_ROOT = path.join(PACKAGE_ROOT, "reports");
const TEMP_ROOT = path.join(PACKAGE_ROOT, ".independent-audit-tmp");
const EXCLUDED = new Set(["node_modules", "out", "cache", "dist", ".git", "__pycache__"]);
const NON_CODE = new Set();

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
      else assert.fail(`Unsupported filesystem entry: ${absolute}`);
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

function fileHash(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function run(executable, args, cwd = PACKAGE_ROOT) {
  const command = [executable, ...args].join(" ");
  const invokedExecutable = process.platform === "win32" && executable.endsWith(".cmd") ? (process.env.ComSpec ?? "cmd.exe") : executable;
  const invokedArgs = process.platform === "win32" && executable.endsWith(".cmd") ? ["/d", "/s", "/c", command] : args;
  const result = spawnSync(invokedExecutable, invokedArgs, {
    cwd,
    encoding: "utf8",
    shell: false,
    env: { ...process.env, NO_COLOR: "1", npm_config_audit: "false", npm_config_fund: "false", npm_config_update_notifier: "false" },
  });
  assert.equal(result.status, 0, `${command} failed in ${cwd}\n${result.stdout ?? ""}\n${result.stderr ?? ""}`);
  return { command, status: "PASS" };
}

function archiveMembers(archivePath) {
  const listing = run("tar", ["-tf", archivePath]);
  const listed = spawnSync("tar", ["-tf", archivePath], { encoding: "utf8", shell: false });
  assert.equal(listed.status, 0, `Unable to list ${archivePath}`);
  const members = listed.stdout.split(/\r?\n/).filter(Boolean);
  assert.ok(members.length > 0, `Empty archive: ${archivePath}`);
  for (const member of members) {
    assert.equal(member.includes("\\"), false, `Backslash archive path: ${member}`);
    assert.equal(member.startsWith("/"), false, `Absolute archive path: ${member}`);
    assert.equal(/^[A-Za-z]:/.test(member), false, `Drive archive path: ${member}`);
    const parts = member.split("/");
    assert.equal(parts.includes(".."), false, `Traversal archive path: ${member}`);
    assert.equal(parts.some((part) => part.toLowerCase() === ".git"), false, `Git metadata in archive: ${member}`);
  }
  const verbose = spawnSync("tar", ["-tvf", archivePath], { encoding: "utf8", shell: false });
  assert.equal(verbose.status, 0, `Unable to inspect member modes for ${archivePath}`);
  for (const line of verbose.stdout.split(/\r?\n/).filter(Boolean)) assert.notEqual(line[0], "l", `Symlink member in ${archivePath}: ${line}`);
  return { members, listing };
}

function extractArchive(archivePath, destination) {
  fs.mkdirSync(destination, { recursive: true });
  archiveMembers(archivePath);
  run("tar", ["-xf", archivePath, "-C", destination]);
}

function lifecycle(stateNode) {
  return stateNode.lifecycle_status ?? "OBSERVED";
}

function slugify(value) {
  return value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").replace(/-{2,}/g, "-");
}

function normalizedDescriptor(requirementGraph, stateNode) {
  return {
    key: slugify(requirementGraph.title),
    title: requirementGraph.title,
    family: requirementGraph.family_id,
    lifecycle: lifecycle(stateNode),
    components: stateNode.scope?.components ?? [],
    contexts: stateNode.scope?.contexts ?? [],
    configuration: stateNode.attributes ?? {},
    ambiguities: Object.values(stateNode.ambiguity ?? {}).map((item) => ({ status: item.status, dimension: item.dimension, description: item.description })),
    execution: stateNode.execution ? { status: stateNode.execution.status, observed_behavior: stateNode.execution.observed_behavior } : null,
  };
}

function shouldProject(requirementId, stateNode) {
  return !NON_CODE.has(requirementId) && !new Set(["REMOVED", "DEFERRED"]).has(lifecycle(stateNode));
}

async function importFresh(modulePath, suffix) {
  return import(`${pathToFileURL(modulePath).href}?audit=${encodeURIComponent(suffix)}`);
}

function assertNoSecrets(root) {
  const patterns = [
    /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/i,
    /AKIA[0-9A-Z]{16}/,
    /gh[pousr]_[A-Za-z0-9]{30,}/,
    /xox[baprs]-[A-Za-z0-9-]{20,}/,
    /sk-[A-Za-z0-9_-]{32,}/,
    /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i,
    /(?:password|passwd|pwd)\s*[:=]\s*(?!placeholder|example|not-set)[^\s]{6,}/i,
    /https?:\/\/[A-Za-z0-9.-]+\.(?:com|net|org|io|ai|co|dev|app)\b/i,
    /\b(?:username|account(?:_name)?)\s*[:=]\s*(?!placeholder|example)[A-Za-z0-9_.@-]{3,}/i,
    /(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}/,
    /\[(?:PASSWORD|ACCOUNT|EMAIL)_\d+\]/i,
  ];
  for (const file of listFiles(root)) {
    const bytes = fs.readFileSync(file.absolute);
    if (bytes.includes(0)) continue;
    const text = bytes.toString("utf8");
    for (const pattern of patterns) assert.equal(pattern.test(text), false, `Possible secret/PII in ${file.relative}: ${pattern}`);
  }
}

function assertZeroDomain(root) {
  const forbidden = [
    "actia", "landing-page", "landing page", "sign-up", "cognito", "provisioning", "console shell", "dashboard",
    "alan sans", "plus jakarta", "frequency", "pulse green", "signal purple", "website footer", "legal document",
    "communication diagram", "cycle diagram", "how it works", "cloudfront", "emeryville",
  ];
  for (const file of listFiles(root)) {
    const bytes = fs.readFileSync(file.absolute);
    if (bytes.includes(0)) continue;
    const lower = bytes.toString("utf8").toLowerCase();
    for (const term of forbidden) assert.equal(lower.includes(term), false, `C_env leakage '${term}' in ${file.relative}`);
  }
}

function featureByKey(snapshot, key) {
  const feature = snapshot.features.find((item) => item.key === key);
  assert.ok(feature, `Missing capability ${key}`);
  return feature;
}

function assertSemanticBoundaries(snapshots) {
  const t001 = snapshots.get(`${PROJECT_ID}_T001`);
  const t001Shell = featureByKey(t001, "console-shell-visual-design");
  assert.equal(t001.features.some((item) => item.key === "responsive-landing-page-layout"), false);
  assert.equal(t001.features.some((item) => item.key === "shared-visual-foundation-for-website-pages"), false);
  assert.equal(t001.features.some((item) => item.key === "cross-page-responsive-design-rules"), false);
  assert.equal("design_coverage" in t001Shell.configuration, false);
  assert.deepEqual(t001Shell.configuration.theme_modes, ["light", "dark"]);

  const t002 = snapshots.get(`${PROJECT_ID}_T002`);
  const t002Responsive = featureByKey(t002, "responsive-landing-page-layout");
  const t002Foundation = featureByKey(t002, "shared-visual-foundation-for-website-pages");
  const t002Footer = featureByKey(t002, "shared-website-footer");
  const t002Shell = featureByKey(t002, "console-shell-visual-design");
  assert.match(t002Responsive.configuration.responsive_behavior, /must include responsive behavior/);
  assert.equal("page_theme" in t002Foundation.configuration, false);
  assert.deepEqual(t002Footer.configuration, {});
  assert.equal(t002Footer.lifecycle, "OBSERVED");
  assert.equal(t002Footer.execution?.status, "CLAIMED_WORKING");
  assert.deepEqual(t002Shell.configuration.design_coverage, ["dashboard_shell", "dashboard_canvas"]);

  const t003 = snapshots.get(`${PROJECT_ID}_T003`);
  const t003Foundation = featureByKey(t003, "shared-visual-foundation-for-website-pages");
  const t003Footer = featureByKey(t003, "shared-website-footer");
  const t003SignIn = featureByKey(t003, "aws-cognito-sign-in-page-styling");
  const t003Wizard = featureByKey(t003, "account-provisioning-wizard-styling");
  assert.equal(t003Foundation.configuration.page_theme, "preserve the landing page's dark theme");
  assert.equal(t003Footer.configuration.site_navigation_location, "footer instead of header");
  assert.equal("branding_content" in t003Footer.configuration, false);
  assert.equal(t003.features.some((item) => item.key === "legal-document-access"), false);
  assert.equal(t003SignIn.execution?.status, "FAILED");
  assert.equal("page_purpose" in t003SignIn.configuration, false);
  assert.equal(t003Wizard.ambiguities[0]?.dimension, "VALUE");
  assert.equal("page_purpose" in t003Wizard.configuration, false);

  const t004 = snapshots.get(`${PROJECT_ID}_T004`);
  const t004Footer = featureByKey(t004, "shared-website-footer");
  assert.equal(t004Footer.configuration.background_treatment, "solid dark gray");
  assert.equal(t004Footer.lifecycle, "OBSERVED");
  assert.equal(t004Footer.ambiguities[0]?.dimension, "VALUE");
  assert.match(t004Footer.ambiguities[0]?.description, /dark purple/);

  const t005 = snapshots.get(`${PROJECT_ID}_T005`);
  const communication = featureByKey(t005, "customer-and-staff-communication-diagram");
  const cycle = featureByKey(t005, "clockwise-cycle-diagram");
  assert.equal(communication.ambiguities[0]?.dimension, "VALUE");
  assert.equal("optional_customer_labels" in communication.configuration, false);
  assert.equal("optional_staff_labels" in communication.configuration, false);
  assert.equal("directional_arrows" in cycle.configuration, false);
}

const graph = readJson(GRAPH_PATH);
const gold = readJson(GOLD_PATH);
const graphByRequirement = new Map(graph.requirement_graphs.map((item) => [item.requirement_id, item]));
const stateById = new Map(graph.requirement_graphs.flatMap((requirementGraph) => requirementGraph.nodes.map((stateNode) => [stateNode.state_id, { requirementGraph, stateNode }])));
const eventById = new Map(graph.requirement_graphs.flatMap((requirementGraph) => requirementGraph.edges.map((event) => [event.event_id, event])));
const goldById = new Map(gold.task_gold_states.map((item) => [item.target_id, item]));
const targetIndex = readJson(path.join(REPORTS_ROOT, "target_index.json"));
const outerValidation = readJson(path.join(REPORTS_ROOT, "validation_report.json"));
const sourceChecksumReport = readJson(path.join(REPORTS_ROOT, "source_checksums.json"));
assert.equal(String(outerValidation.overall).toLowerCase(), "pass");
assert.ok(Array.isArray(targetIndex));
assert.equal(new Set(targetIndex.map((item) => item.target_id)).size, targetIndex.length);
assert.deepEqual(new Set(targetIndex.map((item) => item.target_id)), new Set(goldById.keys()));
for (const artifact of Object.values(sourceChecksumReport.artifacts)) {
  const absolute = path.resolve(WORKSPACE_ROOT, ...artifact.path.split("/"));
  assert.ok(absolute.startsWith(WORKSPACE_ROOT + path.sep));
  assert.equal(fs.statSync(absolute).size, artifact.bytes);
  assert.equal(fileHash(absolute), artifact.sha256);
}
for (const requiredDesignKey of ["deliveredDesign01", "deliveredDesign02", "deliveredDesign03", "deliveredDesign04"]) assert.ok(sourceChecksumReport.artifacts[requiredDesignKey]);

assert.equal(path.dirname(TEMP_ROOT), PACKAGE_ROOT);
fs.rmSync(TEMP_ROOT, { recursive: true, force: true });
fs.mkdirSync(TEMP_ROOT, { recursive: true });

const npmExecutable = process.platform === "win32" ? "npm.cmd" : "npm";
const targetSummaries = [];
const snapshots = new Map();

try {
  const targetDirectories = fs.readdirSync(TARGETS_ROOT, { withFileTypes: true }).filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort();
  assert.equal(targetDirectories.length, gold.task_gold_states.length);

  for (const directoryName of targetDirectories) {
    const targetRoot = path.join(TARGETS_ROOT, directoryName);
    const manifest = readJson(path.join(targetRoot, "manifest.json"));
    const targetGold = goldById.get(manifest.target_id);
    assert.ok(targetGold, `Unexpected target ${manifest.target_id}`);
    assert.equal(manifest.before_message_id, targetGold.target_task.source_message_id);
    assert.deepEqual(manifest.target_event_ids, targetGold.task_event_ids);
    assert.deepEqual(manifest.target_event_types, targetGold.task_event_ids.map((eventId) => eventById.get(eventId)?.event_type));
    assert.equal(manifest.pre_state_verified_against_gold, true);
    assert.equal(manifest.post_state_verified_against_gold, true);
    assert.match(manifest.repo_sha256, /^[0-9a-f]{64}$/);
    assert.equal(manifest.rq4_eligible, targetGold.primary_rq_targets.includes("RQ4"));

    const indexRow = targetIndex.find((item) => item.target_id === manifest.target_id);
    assert.ok(indexRow);
    for (const field of ["before_message_id", "target_event_ids", "target_event_types", "repo_sha256"]) assert.deepEqual(indexRow[field], manifest[field]);

    const expectedState = new Map(targetGold.pre_task_gold_state.requirement_states.map((item) => [item.requirement_id, item.state_id]));
    const mappedState = new Map(manifest.requirements_to_code.map((item) => [item.requirement_id, item.state_id]));
    assert.deepEqual(mappedState, expectedState);
    assert.equal(manifest.tracked_requirement_count, expectedState.size);

    const expandedRoot = path.join(targetRoot, "pre_repo");
    assert.equal(treeHash(expandedRoot), manifest.repo_sha256);
    assertNoSecrets(expandedRoot);
    const extractedRoot = path.join(TEMP_ROOT, manifest.target_id);
    extractArchive(path.join(targetRoot, "pre_repo.zip"), extractedRoot);
    assert.equal(treeHash(extractedRoot), manifest.repo_sha256);
    run(npmExecutable, ["ci", "--ignore-scripts"], extractedRoot);
    run(npmExecutable, ["run", "check"], extractedRoot);

    let projectedCount = 0;
    for (const mapping of manifest.requirements_to_code) {
      const indexedState = stateById.get(mapping.state_id);
      assert.ok(indexedState, `Unknown state ${mapping.state_id}`);
      assert.equal(indexedState.requirementGraph.requirement_id, mapping.requirement_id);
      const expectedProjected = shouldProject(mapping.requirement_id, indexedState.stateNode);
      if (!expectedProjected) {
        assert.deepEqual(mapping.code_paths, []);
        assert.equal(mapping.implementation_mode, NON_CODE.has(mapping.requirement_id) ? "non_code_external_action" : "excluded_lifecycle");
        continue;
      }
      projectedCount += 1;
      assert.equal(mapping.implementation_mode, "simulated_executable");
      const featurePath = mapping.code_paths[0];
      assert.ok(featurePath.startsWith("apps/site/src/features/"));
      const absoluteFeaturePath = path.join(extractedRoot, ...featurePath.split("/"));
      assert.ok(fs.existsSync(absoluteFeaturePath), `Missing mapped code path ${featurePath}`);
      const actualDescriptor = (await importFresh(absoluteFeaturePath, `${manifest.target_id}-${mapping.requirement_id}`)).default;
      assert.deepEqual(JSON.parse(JSON.stringify(actualDescriptor)), normalizedDescriptor(indexedState.requirementGraph, indexedState.stateNode));
    }
    assert.equal(projectedCount, manifest.active_code_feature_count);

    const runtime = await importFresh(path.join(extractedRoot, "apps", "site", "src", "runtime.mjs"), manifest.target_id);
    assert.equal(runtime.snapshot.features.length, manifest.active_code_feature_count);
    snapshots.set(manifest.target_id, JSON.parse(JSON.stringify(runtime.snapshot)));
    targetSummaries.push({
      target_id: manifest.target_id,
      before_message_id: manifest.before_message_id,
      rq4_eligible: manifest.rq4_eligible,
      tracked_requirement_count: manifest.tracked_requirement_count,
      projected_feature_count: manifest.active_code_feature_count,
      tree_hash_matches_expanded_and_archive: true,
      clean_install_build_and_tests: "PASS",
      graph_descriptor_projection: "PASS",
    });
  }

  assertSemanticBoundaries(snapshots);

  const cenvExtracted = path.join(TEMP_ROOT, "cenv");
  extractArchive(CENV_ARCHIVE, cenvExtracted);
  const cenvRoot = path.join(cenvExtracted, `${PROJECT_ID}_C_env_complete`);
  const cenvProject = path.join(cenvRoot, "project");
  const cenvManifest = readJson(path.join(cenvRoot, "reconstruction_audit", "cenv_manifest.json"));
  const cenvValidation = readJson(path.join(cenvRoot, "reconstruction_audit", "validation_report.json"));
  assert.equal(String(cenvValidation.overall).toLowerCase(), "pass");
  assert.equal(treeHash(cenvProject), cenvManifest.project_sha256);
  assert.equal(cenvManifest.project_sha256, outerValidation.c_env.project_sha256);
  assertNoSecrets(cenvProject);
  assertZeroDomain(cenvProject);
  run(npmExecutable, ["ci", "--ignore-scripts"], cenvProject);
  run(npmExecutable, ["run", "check"], cenvProject);
  const cenvRuntime = await importFresh(path.join(cenvProject, "apps", "site", "src", "runtime.mjs"), "cenv");
  assert.deepEqual(cenvRuntime.snapshot.features, []);

  const report = {
    schema_version: "1.0",
    project_id: PROJECT_ID,
    overall: "PASS",
    independence: "This audit reads generated artifacts and canonical Graph/Gold inputs; it does not import the reconstruction generator.",
    c_env: {
      archive_extractable: true,
      archive_paths_safe: true,
      project_tree_hash_matches_manifest: true,
      zero_domain_feature_count: 0,
      zero_domain_leakage_scan: "PASS",
      secret_and_pii_scan: "PASS",
      clean_install_build_and_tests: "PASS",
    },
    targets: targetSummaries,
    exact_gold_target_set: true,
    exact_gold_pre_state_maps: true,
    exact_gold_event_ids_and_types: true,
    semantic_boundary_assertions: "PASS",
    archive_expanded_tree_equivalence: "PASS",
    source_artifact_checksums: "PASS",
    delivered_design_png_count: 4,
    rq4_target_ids: gold.task_gold_states.filter((item) => item.primary_rq_targets.includes("RQ4")).map((item) => item.target_id),
  };
  writeJson(path.join(REPORTS_ROOT, "independent_audit_report.json"), report);
  process.stdout.write(`PASS: independent audit verified C_env and ${targetSummaries.length} target archives for ${PROJECT_ID}.\n`);
} finally {
  fs.rmSync(TEMP_ROOT, { recursive: true, force: true });
}
