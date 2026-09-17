const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const root = process.cwd();

function readJson(file) {
  let raw = fs.readFileSync(file, "utf8");
  // One source message contains a malformed CSS content declaration.  The task
  // package copied that source quote without escaping its closing quote.
  raw = raw.replace('content:\\"鉁揬";\\nposition', 'content:\\"鉁揬\\";\\nposition');
  return JSON.parse(raw);
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonical(value[key])]),
    );
  }
  return value;
}

function sha256(value) {
  return crypto.createHash("sha256").update(value, "utf8").digest("hex");
}

function queueHash(index) {
  const body = { ...index };
  delete body.generated_at;
  return sha256(JSON.stringify(canonical(body)));
}

function occurrence(text, source, entityType, policy, normalizedValue, linkHint = null, nth = 0) {
  let start = -1;
  let cursor = 0;
  for (let index = 0; index <= nth; index += 1) {
    start = text.indexOf(source, cursor);
    if (start < 0) throw new Error(`source not found: ${source}`);
    cursor = start + source.length;
  }
  return {
    source,
    start,
    end: start + source.length,
    entity_type: entityType,
    policy,
    normalized_value: normalizedValue,
    link_hint: linkHint,
    confidence: "HIGH",
  };
}

function existingSemantics(projectId, ordinal) {
  const file = path.join(
    root,
    "outputs",
    "pii_runs",
    projectId,
    "phase1a_message_semantics",
    "messages",
    `${String(ordinal).padStart(5, "0")}.json`,
  );
  return readJson(file).body;
}

const manualSemantics43711852 = {
  ordinal: 22,
  message_id: 22,
  speech_act: "REQUEST",
  polarity: "AFFIRMATIVE",
  execution_status: "NOT_STARTED",
  ambiguity_kind: "NONE",
  decisions: [
    {
      kind: "CHANGE",
      statement: "soften both print treatments and combine the preferred weave tone with the larger scale",
      slot_names: ["WEAVE_PATTERN_SCALE"],
    },
  ],
  slots: [
    {
      slot_name: "WEAVE_PATTERN_SCALE",
      value_type: "DIMENSION",
      source_literal: "5cm",
      start: 1231,
      end: 1234,
      meaning: "preferred scale of the diagonal weave pattern",
      unit: "cm",
      op: "MODIFY",
    },
    {
      slot_name: "WEAVE_PATTERN_SCALE",
      value_type: "DIMENSION",
      source_literal: "5cm",
      start: 1345,
      end: 1348,
      meaning: "larger weave scale to combine with the preferred tone",
      unit: "cm",
      op: "MODIFY",
    },
  ],
  relations: [],
  semantic_facts: [
    {
      kind: "CONSTRAINT",
      statement: "both prints should have less contrast, more grain and texture, softer edges and a less polished vector appearance",
      polarity: "AFFIRMATIVE",
      must_preserve_terms: [],
    },
    {
      kind: "CONSTRAINT",
      statement: "the zebra treatment should use the larger organic stripe direction with a softer bronze or sandy caramel tone",
      polarity: "AFFIRMATIVE",
      must_preserve_terms: [],
    },
    {
      kind: "CONSTRAINT",
      statement: "the weave should move away from orange and red toward a deeper brushed brown tone",
      polarity: "AFFIRMATIVE",
      must_preserve_terms: [],
    },
    {
      kind: "MECHANISM",
      statement: "the preferred weave combines the smaller option's colour treatment with the larger option's scale",
      polarity: "AFFIRMATIVE",
      must_preserve_terms: [],
    },
  ],
};

const specs = [
  {
    project: "43424400",
    ordinal: 15,
    occurrences: (text) => [occurrence(text, "zoom", "NON_PII", "PRESERVE", "zoom")],
  },
  {
    project: "43711852",
    ordinal: 22,
    semantics: manualSemantics43711852,
    occurrences: (text) => [
      occurrence(text, "Orne", "PERSON", "SYNTHESIZE", "Orne", "PERSON_1"),
      occurrence(text, "TELA MARE", "PROJECT_NAME", "SYNTHESIZE", "TELA MARE", "PROJECT_1"),
      occurrence(text, "stripe", "NON_PII", "PRESERVE", "stripe"),
    ],
  },
  {
    project: "43945601",
    ordinal: 45,
    occurrences: (text) => [occurrence(text, "zoom", "NON_PII", "PRESERVE", "zoom")],
  },
  {
    project: "43945601",
    ordinal: 47,
    occurrences: (text) => [
      occurrence(text, "Abdulbari", "PERSON", "SYNTHESIZE", "Abdulbari", "PERSON_1"),
      occurrence(text, "zoom", "NON_PII", "PRESERVE", "zoom"),
    ],
  },
  {
    project: "43969153",
    ordinal: 54,
    occurrences: (text) => [occurrence(text, "zoom", "NON_PII", "PRESERVE", "zoom")],
  },
  {
    project: "44039904",
    ordinal: 2,
    occurrences: (text) => [occurrence(text, "meta", "NON_PII", "PRESERVE", "meta")],
  },
  {
    project: "44128864",
    ordinal: 97,
    occurrences: (text) => [occurrence(text, "zoom", "NON_PII", "PRESERVE", "zoom")],
  },
  {
    project: "44128864",
    ordinal: 115,
    occurrences: (text) => [
      occurrence(text, "Jimena", "PERSON", "SYNTHESIZE", "Jimena", "PERSON_1"),
      occurrence(text, "zoom", "NON_PII", "PRESERVE", "zoom"),
    ],
  },
  {
    project: "44133873",
    ordinal: 94,
    occurrences: (text) => [occurrence(text, "zoom", "NON_PII", "PRESERVE", "zoom")],
  },
  {
    project: "44151581",
    ordinal: 49,
    occurrences: (text) => {
      const checkout = "https://jim-liao-ddb0.mykajabi.com/offers/KdYiXWjK/checkout";
      const fonts = "https://fonts.googleapis.com/css2?family=Oswald:wght@500;600&amp;family=Montserrat:wght@500;600;700;800&amp;display=swap";
      return [
        occurrence(text, "Conscious Coaches Academy", "PROJECT_NAME", "SYNTHESIZE", "Conscious Coaches Academy", "PROJECT_1"),
        occurrence(text, checkout, "PRIVATE_URL", "SYNTHESIZE", checkout, "PROJECT_1", 0),
        occurrence(text, checkout, "PRIVATE_URL", "SYNTHESIZE", checkout, "PROJECT_1", 1),
        occurrence(text, checkout, "PRIVATE_URL", "SYNTHESIZE", checkout, "PROJECT_1", 2),
        occurrence(text, fonts, "PUBLIC_TECHNOLOGY", "PRESERVE", fonts),
        occurrence(text, "@import", "NON_PII", "PRESERVE", "@import"),
        occurrence(text, "@media", "NON_PII", "PRESERVE", "@media"),
      ];
    },
  },
];

const byProject = new Map();
for (const spec of specs) {
  const runDir = path.join(root, "outputs", "pii_runs", spec.project);
  const taskFile = path.join(runDir, "agent_tasks", `task_${String(spec.ordinal).padStart(5, "0")}.json`);
  const task = readJson(taskFile);
  const semantics = spec.semantics || existingSemantics(spec.project, spec.ordinal);
  const repairs = byProject.get(spec.project) || [];
  repairs.push({
    task_id: task.task_id,
    kind: "EXTRACTION",
    ordinal: spec.ordinal,
    message_id: task.message_id,
    safe_source_sha256: task.safe_source_sha256,
    plan_slice_sha256: null,
    author: "codex-agent",
    reason: "Supplied complete offline discovery and semantic annotations for the failed extraction message.",
    annotation: {
      occurrences: spec.occurrences(task.safe_original_text),
      semantics,
    },
  });
  byProject.set(spec.project, repairs);
}

for (const [project, repairs] of byProject) {
  const runDir = path.join(root, "outputs", "pii_runs", project);
  const index = readJson(path.join(runDir, "agent_tasks", "index.json"));
  const output = {
    schema_version: "pii-agent-repairs-v1",
    project_id: project,
    queue_sha256: queueHash(index),
    repairs,
    blocked: [],
  };
  const directory = path.join(runDir, "agent_repairs");
  fs.mkdirSync(directory, { recursive: true });
  const outputPath = path.join(directory, "repairs.json");
  fs.writeFileSync(outputPath, `${JSON.stringify(output, null, 2)}\n`, "utf8");
  const roundTrip = JSON.parse(fs.readFileSync(outputPath, "utf8"));
  if (roundTrip.queue_sha256 !== queueHash(index)) {
    throw new Error(`${project}: queue hash did not round-trip`);
  }
  for (const repair of roundTrip.repairs) {
    const taskFile = path.join(
      runDir,
      "agent_tasks",
      `task_${String(repair.ordinal).padStart(5, "0")}.json`,
    );
    const task = readJson(taskFile);
    if (task.safe_source_sha256 !== repair.safe_source_sha256) {
      throw new Error(`${repair.task_id}: source hash mismatch`);
    }
    for (const item of repair.annotation.occurrences) {
      if (task.safe_original_text.slice(item.start, item.end) !== item.source) {
        throw new Error(`${repair.task_id}: bad occurrence span`);
      }
    }
    for (const slot of repair.annotation.semantics.slots || []) {
      if (task.safe_original_text.slice(slot.start, slot.end) !== slot.source_literal) {
        throw new Error(`${repair.task_id}: bad semantic slot span`);
      }
    }
  }
  console.log(`${project}: ${roundTrip.repairs.length} repair(s) validated`);
}

console.log(`wrote ${specs.length} extraction repairs across ${byProject.size} projects`);
