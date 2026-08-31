# Scope and Timeline

Written after the product owner's answers of 27 July. This file exists separately because it is a decision to be made, not a finding to be read.

---

## 1. What was confirmed

| Question asked | Answer | Effect on the audit |
| --- | --- | --- |
| Is multi-user in Release 1? | **Yes** | `A-12`, `A-22`, `A-23` become hard blockers; three missing backend endpoints become R1 work |
| Is instant revocation required from day one? | **Yes** | Open backend issue #1427 becomes an R1 blocker (`A-24`) |
| Was an owner-facing metering view planned? | **Replaced by a new requirement: BIQc Wallet** | Net-new subsystem, not a readiness fix (`A-25`) |

**BIQc Wallet as described:** anyone with Governance/Admin access can purchase credit and allocate credits to particular users, with auto top-up available.

A clarification worth recording, because it will otherwise blur: the existing per-member metering in the superadmin console and the Wallet are not the same thing. Wallet is absent from the codebase entirely — not partially built, not built for the wrong role. Nothing in it can be reached by adjusting permissions on what exists.

## 2. What this means

**Multi-user makes the team-access chain a blocker.** Four separate breaks, three of them backend work that has not started: the invite surface is unreachable on the deployment (`A-12`); the live invite endpoint does not enforce the role contract in its own source (`A-22`); no acceptance route exists for an invited user to land on (`A-23`); and member-list, revoke and remove endpoints do not exist (`A-23`).

**Instant revocation makes #1427 a blocker.** Today disconnect returns success without removing the connection record. The front end handles this correctly and refuses to display success, so the user-visible outcome is that revocation does not complete. Either the backend issue is fixed before launch, or the claim comes out of the product description until it is. Shipping both together puts a security-adjacent marketing statement in conflict with system behaviour.

**Wallet is new scope with a fixed dependency order.** Credits cannot be allocated to members who cannot be listed, invited or removed. Team access has to work before Wallet can be built on it — this is not a sequencing preference, it is a data-model constraint.

## 3. Against four working days

| Item | State |
| --- | --- |
| Front-end blockers already identified | 64–128 hours |
| Member-list, revoke, remove endpoints | Do not exist |
| Instant revocation | Blocked by #1427 |
| BIQc Wallet, front end | 60–100 hours, not started |
| BIQc Wallet, backend ledger | Not started, not estimated |
| Branch protection | Not in place |

Most of the remaining work is backend, concentrated on one developer, so it cannot be parallelised away. The confirmed scope is a multi-week programme.

## 4. Two paths

**Path A — hold the date, cut the scope.**
Ship a single-tenant Release 1: one account, one owner, no invitations, no Wallet. This is reachable in a short window, because what stands in the way is drift and configuration rather than missing capability — steps 0 to 3 of the remediation plan. Instant revocation still needs a decision: either #1427 is fixed or the claim is withdrawn from the description, and the second option costs nothing but a copy edit. Multi-user and Wallet become Release 1.1 with a date set from Anjali's estimates.

**Path B — hold the scope, move the date.**
Multi-user, instant revocation and Wallet all in. A date cannot responsibly be set until the backend items are estimated. What can be said now is that the front-end portion alone is 192–341 hours against confirmed scope, and the backend portion is larger.

**The path I would avoid** is deploying the announced scope on the announced date. The specific risks are not cosmetic:

- an invited user follows a link and lands nowhere
- a customer revokes access, sees success, and the access remains
- a credit balance behaves unpredictably when two members spend against it at once

The third is money, and it is the one that does not stay quiet. Concurrency defects in a credit ledger surface as customer-visible billing errors or as revenue leaking without anyone noticing until reconciliation.

## 5. Regardless of path

Close `main` with branch protection, required review and a required status check. Two to three hours. It is independent of scope, independent of date, and it is the only measure that prevents the findings in this audit from reproducing themselves. Issue #1533 already names it.

## 6. Three decisions that set the date

These belong to the team, not to this audit. They are listed because a release date is not meaningful until all three are settled.

1. **Path A or Path B.** This determines whether the remaining findings are launch blockers or backlog. Everything else in the plan follows from it.
2. **A backend estimate** for the three missing multi-user endpoints, #1427, and the Wallet ledger. These sit with the developer who will build them; no date is real without those numbers.
3. **A Wallet specification**, if Wallet stays in R1. The questions listed in `06_ASSUMPTIONS_EXCLUSIONS_AND_DECISIONS.md` determine the data model, so they need answers before the build starts rather than during it.

This audit is complete as delivered and requires no further input to be actionable. Post-audit development sits outside the engagement.
