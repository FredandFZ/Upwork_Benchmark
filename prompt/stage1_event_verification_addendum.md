# ReqMemBench EVENT_VERIFICATION Addendum

Apply this addendum only when `RUN_MODE = EVENT_VERIFICATION`. It supplements the common Stage 1 prompt and takes precedence if a generic short-acceptance rule would otherwise permit weak target alignment.

## 1. Source-primary target entailment

Judge the Event's `source_message` first. `supporting_message_ids` may resolve a genuinely short and tightly coupled reference, but they must not carry essentially all of the target-specific meaning while the source message substantively discusses other work.

Return `DELETE` when:

- the only connection to the target is a generic opener such as `cool`, `okay`, `great`, `sounds good`, or `thanks`;
- the substantive body of the source message moves to unrelated payments, testing, content, scheduling, or other Requirements;
- elapsed time, intervening context, multiple open proposals, or a topic shift makes the alleged acceptance non-unique;
- removing the supporting messages would leave no target-specific proposition in the source message;
- the source supports an Event, but not an Event for `TARGET_REQUIREMENT`.

Example: a freelancer proposes removing an integration; a later client message begins with `cool` but then discusses phase payment, testing, FAQs, and website copy. The later message is not reliable source evidence for a `REMOVE` Event unless it explicitly accepts the integration removal. Delete the misaligned Event rather than letting supporting context supply its entire meaning.

## 2. Audit challenges are active verification inputs

`EVIDENCE_INDEX.audit_review_items` contains unresolved concerns emitted by `CONSISTENCY_AUDIT` for this target. Independently resolve each applicable concern against `LOCAL_CONTEXT`.

- Do not automatically copy the Audit conclusion.
- Do not ignore a target-specific Audit warning.
- When Audit identifies source/target misalignment and the source fails the source-primary gate above, return `DELETE`.
- Use `KEEP` only when the source and tightly coupled context clearly entail this exact Requirement and Event operation.

## 3. Execution Event sparsity check

Apply a final necessity test to every `IMPLEMENTATION_CLAIM`, `RUNTIME_FAILURE`, and `RUNTIME_VERIFICATION`:

- `DELETE` generic progress, availability, payment, or "done" messages that do not entail the target behavior.
- `DELETE` repeated observations that add no new path, failure mode, post-fix persistence, regression, or target-specific verification.
- `DELETE` broad end-to-end status Events when the evidence establishes only a narrower sub-behavior.
- Keep distinct failure/fix/retest transitions when they materially change the Requirement's observed state.

Accuracy takes priority over preserving lifecycle length. Do not keep a weak Event merely to prevent the Requirement from falling below the pipeline's minimum-Event threshold.
