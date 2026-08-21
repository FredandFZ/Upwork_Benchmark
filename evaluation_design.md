# Evaluation Design for ReqMemBench Pilot

## Evaluation principle

The five RQs are not five unrelated datasets. They are five diagnostic views over the same longitudinal project history.

The benchmark uses three layers:

1. **Requirement State Understanding** — RQ1, RQ2, RQ3
2. **Action Decision** — RQ4
3. **Executable / Behavioral Outcome** — RQ5

## RQ1 — Relevant Requirement Selection

**Input:** current milestone task + mixed prior history.

**Output:** selected historical message IDs and critical evidence IDs.

**Metrics:**
- History Precision
- History Recall
- History F1
- Critical Evidence Recall

**Pilot score:** `0.6 * F1 + 0.4 * Critical Recall`.

## RQ2 — Requirement Scope & Persistence

**Input:** a current decision plus earlier requirement evidence.

**Output:** scope label, whether the requirement applies now, and supporting evidence.

**Labels:**
- `SESSION_LOCAL`
- `MILESTONE_PERSISTENT`
- `PROJECT_PERSISTENT`
- `DOMAIN_SCOPED`
- `UNKNOWN`

**Metrics:**
- Scope Accuracy
- Applicability Accuracy
- Evidence F1

**Pilot score:** `0.45 * ScopeAcc + 0.35 * ApplicabilityAcc + 0.20 * EvidenceF1`.

## RQ3 — Temporal Validity & Conflict Resolution

**Input:** chronological versions of a requirement.

**Output:** currently valid state, active evidence, and superseded evidence.

**Metrics:**
- Current-state field accuracy
- Active-evidence F1
- Superseded-evidence F1

**Pilot score:** `0.60 * StateAcc + 0.20 * ActiveF1 + 0.20 * SupersededF1`.

## RQ4 — Memory-or-Clarify Decision

**Input:** history available at the decision point.

**Output:** one of:
- `USE`
- `IGNORE`
- `OVERRIDE`
- `CLARIFY`

**Metrics:**
- Action Accuracy / Macro-F1 when scaled
- Evidence F1

**Pilot score:** `0.80 * ActionAcc + 0.20 * EvidenceF1`.

When the dataset is scaled, report the confusion matrix because `USE -> CLARIFY` (unnecessary clarification) and `CLARIFY -> USE` (unsupported assumption) have different meanings.

## RQ5 — Requirement-to-Code Traceability

**Input:** requirement history plus implementation/runtime evidence available at that point.

**Output:**
- requirement status: `IMPLEMENTED`, `PARTIALLY_IMPLEMENTED`, `FAILED_AT_RUNTIME`, `VERIFIED`
- failure stage: `NONE`, `RETRIEVAL`, `SELECTION`, `VALIDITY`, `INTERPRETATION`, `IMPLEMENTATION`, `ORCHESTRATION`, `VERIFICATION`
- evidence level: `L1_CODE_TEST`, `L2_RUNTIME`, `L3_DOCUMENTARY`

**Metrics:**
- Status Accuracy
- Failure-stage Accuracy
- Evidence-level Accuracy
- Evidence F1

**Pilot score:** `0.40 * StatusAcc + 0.30 * FailureStageAcc + 0.10 * EvidenceLevelAcc + 0.20 * EvidenceF1`.

For the final coding benchmark, RQ5 must additionally include executable requirement-specific tests where repository snapshots are available.

## Overall reporting

Do **not** rely only on one overall score.

Primary report:
- RQ1 score
- RQ2 score
- RQ3 score
- RQ4 score
- RQ5 score
- Functional task success / test pass rate (when executable task is available)

Optional headline number:
- Macro average of the five RQ scores

This preserves diagnostic information and prevents strong retrieval performance from hiding poor execution.
