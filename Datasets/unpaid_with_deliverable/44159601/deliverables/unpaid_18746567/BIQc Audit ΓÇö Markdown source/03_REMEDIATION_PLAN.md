# Remediation Plan

Sequenced so each step makes the next one measurable. The order matters more than the estimates: fixing tests before fixing the build means re-running everything, and fixing routes before settling the toolchain means the verification cannot be reproduced.

---

## Step 0 — Close `main` before anything else
**`H-01` · 2–3 hours · do this regardless of which release path is chosen**

Branch protection on `main`, required review, required status check. Remove the committed `.gitconfig` that assigns agent authorship by default (5 minutes).

This is out of sequence deliberately. Every other step in this plan repairs damage; this one is the only step that stops the damage recurring. Without it, 5,057 agent commits will be joined by more, through the same unguarded path, and a second audit in three months would produce a similar list. Open issue #1533 already names the problem.

Two to three hours, and it is the highest-leverage work in this document.

## Step 1 — One supported toolchain
**`A-01`, `A-03`, `H-05` · 17–29h**

One Node version, one package manager, one install command, working from a clean checkout and identical in CI. Establish which of the four Dockerfiles the deployment pipeline actually uses and delete the rest. Nothing downstream is verifiable until a second engineer can reproduce a run.
*Owner: front end. Blocks steps 2, 3, 4.*

## Step 2 — Repair the production build
**`A-13`, `A-26` · 9–26h**

Isolate the dev-only React Refresh / Babel path from the production pipeline. On the first successful build, capture main-chunk size, verify that the 98 route-level `lazy()` splits survive into emitted chunks, and settle the source-map question.
*Owner: front end.*

## Step 3 — Align the deployed route contract
**`A-15`, `A-16`, `A-17` · 24–40h**

Reconcile route base, redirects and deployment rewrite rules into one source of truth so the named R1 routes resolve as named. Give `admin` an explicit access-restricted state; stop `manage-users` discarding its query context into billing.
*Owner: front end plus deployment. Cannot be completed by the front end alone.*

## Step 4 — Make the team-access chain work end to end
**`A-12`, `A-22`, `A-23` · 28–52h front end, plus backend**

Now a hard blocker: multi-user is confirmed R1 scope.

1. Re-run the invite path on the release candidate once step 3 lands, capturing what the audit could not reach: the `Your role` value, invite submission, the literal `invite_link`, its behaviour in a private window, and email delivery.
2. Build the invite acceptance route and landing surface — neither exists today.
3. Resolve why a `user_admin` bearer reaches seat-tier enforcement rather than failing on the documented `{owner, admin}` gate.
4. **Backend:** member-list, revoke and remove endpoints. These do not exist and are not estimated here.

*Owner: front end plus backend auth.*

## Step 5 — Instant revocation
**`A-24` · backend scope**

Fix #1427 so disconnect endpoints actually remove the connection record, or remove the instant-revocation claim from the product description until they do. The front end already behaves correctly and needs no change.
*Owner: backend.*

## Step 6 — BIQc Wallet
**`A-25` · 60–100h front end, backend substantial**

Cannot start before step 4 completes: credits cannot be allocated to members who cannot be listed, invited or removed.

Sequence within the step: agree the specification (see open questions in `06_...`), then the backend ledger with allocation, per-member enforcement, top-up automation and audit trail, then the front-end purchase, allocation and balance surfaces with Governance/Admin gating.

Concurrency behaviour must be tested explicitly before launch — two members spending against one balance, a top-up landing during consumption, a limit boundary hit by simultaneous requests. These are the failure modes that produce revenue loss or customer-visible billing errors.

## Step 7 — Re-baseline the test inventory
**`A-02`, `A-04`–`A-10` · 22–36h**

Not "make it green". Classify each of the eleven, then act per class: fix the one real violation (`A-04`); delete tests targeting deleted surfaces (`A-05`); update tests behind documented product decisions (`A-06`); resolve contradictions by deciding which expectation is current (`A-07`); fix the false positive (`A-08`); reconcile the copy constants (`A-09`); apply the existing router mock (`A-10`). Then expand the CI gate beyond 7 suites — which is what step 0's required status check depends on.
*Owner: front end.*

## Step 8 — Harden the edge
**`A-18`, `A-19` · 9–18h**

Enforced CSP in place of report-only, inline scripts removed or nonce-based, HSTS on the front-end root, and one layer designated owner of security headers so the duplicates stop.
*Owner: front-end edge plus proxy/backend.*

## Step 9 — Lint gate on changed files
**`A-11` · 8–16h**

Commit a real ESLint config, add a `lint` script, run it in CI, scope enforcement to changed files. Do not attempt the 2,775-issue cleanup before R1 — the two counts that would have justified urgency (`rules-of-hooks`, `no-undef`) are both zero.

## Step 10 — Repository cleanup and small items
**`H-02`–`H-06`, `A-14`, `A-20`, `A-21` · 13–21h · Phase 2**

Delete the failed-command artefacts (10 min). Consolidate the seven `evidence*` directories into `docs/evidence/` with dates (1h). Move root markdown into `docs/` with an index (2h). Remove the 4,674 lines of unreachable code — **after confirming with the developer whether `AdvisorWatchtower.js` is returning in R1** (1h). Update the `shell-quote` override alongside the Dependabot PR rather than merging it alone. Give logged-out protected-route access a clean dedicated redirect. Refresh role state on privilege-sensitive surfaces.

---

## Effort summary

| Workstream | Findings | Priority | Hours | Owner |
| --- | --- | --- | --- | --- |
| **Branch protection and required checks** | H-01 | **P0** | **2–3** | Repo admin |
| Toolchain, CI and build contour | A-01, A-03, H-05 | P0 | 17–29 | Front end |
| Production build repair | A-13, A-26 | P0 | 9–26 | Front end |
| Route and deployment alignment | A-15, A-16, A-17 | P0 | 24–40 | FE + deployment |
| Team-access chain | A-12, A-22, A-23 | P0 | 28–52 | FE + backend |
| Instant revocation (#1427) | A-24 | P0 | backend | Backend |
| BIQc Wallet | A-25 | P0 | 60–100 FE | FE + backend |
| Test inventory re-baseline | A-02, A-04–A-10 | P1 | 22–36 | Front end |
| Edge security hardening | A-18, A-19 | P1 | 9–18 | FE + proxy |
| Lint gate | A-11 | P1 | 8–16 | Front end |
| Repository cleanup and small items | H-02–H-06, A-14, A-20, A-21 | P2 | 13–21 | Front end |
| **Front-end total, confirmed scope** | | | **192–341** | |

Backend items — member-list, revoke, remove, #1427, and the Wallet ledger — are deliberately unestimated. They belong to the developer who will build them, and an outside figure on work I have not scoped would look authoritative and be invented.

Estimates assume one focused front-end engineer with availability from deployment and backend owners. They do not include building a staging environment, which does not exist and is a separate decision.

---

## Exit criteria for Release 1 sign-off

Defensible when all of the following hold **on the release candidate**, not on a developer machine:

1. `main` is protected with required review and a required status check.
2. The production build completes and emits a valid optimized bundle.
3. One documented Node version and one package-manager path work from a clean checkout, and CI uses the same path; one Dockerfile is authoritative.
4. The named Release 1 routes resolve as named.
5. The invite path is reachable, and an invite link has been opened end to end in a private window with the result recorded.
6. An invited user has a landing surface, and the account owner can list, revoke and remove members.
7. Invite authorisation matches the documented role contract, verified by direct endpoint probe.
8. Disconnect actually removes the connection record, or the instant-revocation claim is withdrawn.
9. If Wallet ships: credit allocation and spend behave correctly under simultaneous access, with a written test for the limit boundary.
10. Admin and protected-route failures produce explicit, correct outcomes — not generic 404s, not silent redirects into billing.
11. The test baseline is green, or every remaining red suite has a written, accepted reason.
12. An enforced CSP replaces the report-only posture.

---

## Scope note

Post-audit development is outside the current engagement. If P0 work is to be contracted, the cleanest structure is a separate fixed price for blockers only — steps 0 through 4 — rather than an open-ended engagement. I have no capacity for a large refactor before August, and would not recommend one as part of Release 1 in any case: none of the findings above are solved by rewriting the front end.
