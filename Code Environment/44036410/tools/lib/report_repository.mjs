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

export function renderHints(requirementId, stateNode) {
  const attributes = stateNode.attributes ?? {};
  const hints = {};
  if (requirementId === "REQ_PREMIUM_REPORT_VISUAL_DESIGN") {
    hints.premium = true;
    hints.reportTitle = "Vehicle Security Assessment Report";
    hints.reportCodeLabel = "Report code";
    hints.dateLabel = "Assessment Date";
    hints.riskHeading = "Risk Band";
    hints.dashboardReasonHeading = "What caused this result";
    hints.detailsHeading = "Assessment details";
    hints.subjectLabel = "Vehicle group";
    hints.subjectValue = "Customer-assessed vehicle group";
    hints.contextHeading = "Risk context";
    hints.priorityHeading = "Priority upgrade path";
  }
  if (requirementId === "REQ_FRONT_PAGE_RESULT_DASHBOARD") {
    hints.scoreHeading = typeof attributes.score_heading === "string" ? attributes.score_heading : "Security Score";
    hints.scoreFontSize = /slightly enlarge|main dashboard/i.test(String(attributes.dashboard_prominence ?? "")) ? 46 : 34;
    hints.dashboardFailed = stateNode.execution?.status === "FAILED";
  }
  if (requirementId === "REQ_SCANNABLE_RESULT_EXPLANATION") {
    hints.explanationDense = stateNode.execution?.status === "FAILED";
    hints.explanationItems = stateNode.execution?.status === "FAILED"
      ? ["Extended explanation line one", "Extended explanation line two", "Extended explanation line three", "Extended explanation line four", "Extended explanation line five", "Extended explanation line six"]
      : ["Primary result reason", "Main exposure", "Priority action"];
  }
  if (requirementId === "REQ_VEHICLE_GROUP_PRESENTATION") hints.vehicleUsesCheckboxes = stateNode.execution?.status === "FAILED" || attributes.use_checkbox_form === true;
  if (requirementId === "REQ_DISTRIBUTION_WARNING") {
    hints.warningEnabled = true;
    hints.warningText = typeof attributes.warning_message === "string" ? attributes.warning_message : "Restricted distribution";
    hints.warningStyle = stateNode.execution?.status === "FAILED" ? "heavy" : "subtle";
  }
  if (requirementId === "REQ_EDITABLE_CUSTOMER_FIELDS") {
    hints.assessmentDate = typeof attributes.assessment_date_field === "string" && /\[Assessment Date\]/.test(attributes.assessment_date_field)
      ? "[Assessment Date]"
      : stateNode.execution?.status === "FAILED" ? "Assessment Date: Assessment Date" : "[Assessment Date]";
  }
  if (requirementId === "REQ_INTERNAL_PAGE_HEADER") hints.headerEnabled = true;
  if (requirementId === "REQ_PAGE_FOOTER") hints.footerAllPages = !/missing/i.test(String(stateNode.execution?.observed_behavior ?? ""));
  if (requirementId === "REQ_REPORT_CODE_CONSISTENCY") hints.bodyCode = stateNode.execution?.status === "FAILED" ? "PR-01" : "RR-01";
  if (requirementId === "REQ_INTERNAL_HEADER_CODE_CONSISTENCY" && typeof attributes.rr01_internal_header_code === "string") hints.headerCode = attributes.rr01_internal_header_code;
  if (requirementId === "REQ_FOOTER_CODE_CONSISTENCY" && typeof attributes.rr01_footer_code === "string") hints.footerCode = attributes.rr01_footer_code;
  if (requirementId === "REQ_RISK_APPROPRIATE_REPORT_COPY") hints.copyLines = stringsDeep(attributes).slice(0, 2);
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
  return `# ${repositoryLabel}\n\nThis is a deterministic executable reconstruction of a report-layout state. It is not a recovered historical source repository and it does not seed any pre-event state from the final delivered DOCX/PDF files.\n\nThe repository uses the Node.js standard library only. It generates a real macro-free OOXML \`.docx\` plus a deterministic four-page PDF, exposes behavior-level dashboard/warning/footer/code operations, and keeps one graph-backed module per active requirement state.\n\n## Run\n\n\`\`\`sh\nnpm ci --ignore-scripts\nnpm run check\nnpm run inspect\n\`\`\`\n\nGenerated artifacts are \`artifacts/reconstructed-report.docx\` and \`artifacts/reconstructed-report.pdf\`. The current snapshot contains ${featureCount} projected requirement states. Node.js 20 or newer is required; no network service, Microsoft Office installation, or credential is needed for build and test.\n`;
}

export function createReportRepository(destination, templateRoot, { features, environmentLabel, repositoryLabel, documentLabel }) {
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
    source_policy: "Graph-backed synthetic OOXML/PDF; final deliverable DOCX/PDF files are checksum-only evidence and are not temporal seeds.",
  }));
}
