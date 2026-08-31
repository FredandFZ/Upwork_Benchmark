# BIQc — Front-End Release 1 Readiness Audit

Prepared by: Svitlana Horodylova (front-end contractor)
For: Andre Alexopoulos (product owner), Anjali Kalsariya (developer)
Scope of review: `biqc-ai/Version2-Ai_Mentor` front end, repository organisation, and the `dev.biqc.ai` deployment
Version: 2.0 — 27 July 2026, incorporating the product owner's confirmed Release 1 scope

---

## What this pack is

A written front-end readiness review against the agreed engagement: a Release 1 recommendation, prioritised findings with evidence and file/line references, security / architecture / performance / maintainability risks, remediation with indicative effort, and stated assumptions and exclusions.

No code was changed. No migrations were run. Two temporary measurement artefacts were created locally and not committed.

## How to read it

| File | Written for | Contents |
| --- | --- | --- |
| `01_FOUNDER_SUMMARY.md` | Andre | The decision in plain language: what ships, what doesn't, what it costs, and the one measure I would take before anything else |
| `02_FINDINGS_REGISTER.md` | Anjali + Andre | All 34 findings — Part A code and deployment (`A-01`…`A-25`), Part B repository and process (`H-01`…`H-09`) — each with severity, evidence, R1 consequence and hours |
| `03_REMEDIATION_PLAN.md` | Anjali + deployment owner | Work sequence, effort table, exit criteria for sign-off |
| `04_EVIDENCE_LOG.md` | Anyone verifying the work | What was executed, what it produced, and which earlier hypotheses it disproved |
| `05_SCOPE_AND_TIMELINE.md` | Andre | The end-of-week question, answered with two concrete paths |
| `06_ASSUMPTIONS_EXCLUSIONS_AND_DECISIONS.md` | Both | Audit boundary, what could not be verified, and the decisions the team needs to make |

Both layers share one ID scheme, so a point raised in the founder summary can be continued in the technical register without translation.

## The finding in one paragraph

The front end is not a blank slate. Several Release 1 surfaces are genuinely built, and several engineering decisions in it are better than the team's own description suggests. The blocker is that four sources of truth about this product — the source code, the test gate, the production build, and the live deployment — do not agree with each other. The repository contains a working team-invite implementation the deployment does not expose. The production build does not complete. The named Release 1 routes do not resolve as named. And the reason all of this survived to a pre-release state is measurable: 78% of commits were made by an AI agent, and they reached `main` with no branch protection, no required review and a test gate covering 7 suites out of 170.

## What changed in version 2.0

- The product owner confirmed that **multi-user is in Release 1**, that **instant revocation is required from day one**, and introduced a new requirement, **BIQc Wallet**. Findings previously marked as Phase 2 dependencies are now blockers, and a capability that does not exist in the codebase is now in scope. See `05_SCOPE_AND_TIMELINE.md`.
- A **repository hygiene and project organisation review** was added as Part B of the findings register (`H-01`…`H-09`). It does not add blockers. It explains why the blockers went unnoticed, and it produces the single highest-leverage recommendation in this pack.

## Correction notice

Four claims from earlier working material were tested and did not survive. They are documented as withdrawn in `04_EVIDENCE_LOG.md` rather than quietly dropped:

- the invite flow is **not** missing from the front-end source — it exists; the deployment is the problem
- production console logging does **not** leak tokens or API payloads
- the `useAlerts` / `Advisor` interval-leak hypothesis was **not** confirmed
- the test suite inventory is **170**, not 157, so any "7 of 157" coverage figure must be restated

A shorter list that holds is worth more than a longer one that doesn't.
