# Founder Layer — Release 1 Readiness

Written to be read without technical background. Every claim is backed by a numbered entry in `02_FINDINGS_REGISTER.md`.

---

## 1. The recommendation

**Do not sign off Release 1 for external launch in its current state, and do not target the end of this week for the scope as confirmed.**

A controlled internal demo is realistic today — someone who knows which URLs work can show real, working product. A customer arriving at the advertised addresses will not have that experience.

There is a version of Release 1 that could ship soon. It is not the version currently described. Section 6 sets out the choice.

## 2. Why — in plain terms

The product exists. Ask BIQc answers prompts and correctly refuses to give a decision-safe answer when it has no grounded evidence. Integrations renders a real connector catalogue. Billing shows a real plan and real usage. This is not a hollow demo.

The problem is different in kind, and worth stating precisely because it changes what you should ask for:

> Four sources of truth about this product disagree with each other — the source code, the automated test gate, the production build, and the live deployment.

Concretely:

- The code contains a **working team invitation feature**. The dev site does not let you reach it. (`A-12`)
- The **production build does not finish**. There is no valid, complete production package of the front end today. (`A-13`)
- Several **named Release 1 addresses do not work** when typed or shared — `/settings`, `/team-access`, `/integrations`, `/admin`. The features behind them exist; the doors do not open. (`A-15`, `A-16`, `A-17`)
- The **automated test gate cannot be trusted**: it checks 7 test files out of 170, and part of the wider suite fails for reasons that are mostly old tests arguing with newer product decisions rather than real breakage. (`A-01`, `A-02`, `A-03`)

## 3. Why it went unnoticed — the part I would not skip

A repository review answers the question the rest of the audit raises. The numbers are reproducible:

- **78% of all commits — 5,057 of 6,456 — were made by an AI agent** (`emergent-agent-e1`). The second-largest contributor by volume is you, at 19%. (`H-01`)
- A configuration file committed at the root of the repository **assigns agent authorship to everyone working in that tree by default**, regardless of who actually did the work. Anjali does not appear in the commit history under her own name at any point. (`H-01`)
- 1,308 pull requests have been closed **with no branch protection on `main`**, no required review, and no required status check. Your own issue #1533 already names this.

This is not an argument that machine-written code is bad code. Parts of this codebase are written well, and I have listed them in section 5. It is an argument about the gap between code and production: there is currently nothing standing in it.

That gap is the mechanism. Half of an invitation flow can be missing for months and no one finds out, because no test covers it and the tests that exist don't run. Nine empty files created by a mistyped Windows command are sitting in your repository root right now, committed to `main` (`H-02`). They are harmless in themselves. They are proof that nothing is checking.

**If you take one action from this entire audit, take this one:** close `main` with branch protection, required review and a required full-test status check. It is two to three hours of work. It is the only measure that stops every other finding in this pack from reproducing itself.

## 4. Module readiness

Status from the live dev deployment, not from reading code. "Partially" means the feature works when reached through a working path, but not through its named address.

| Module | Status | Practical issue |
| --- | --- | --- |
| Authentication | Works partially | Login, registration, password reset usable in-app; named auth routes are not stable |
| Sidebar / app shell | Works | Renders and functions |
| Settings (General, Account) | Works partially | Reachable at `/app/settings`, not `/settings` |
| Billing & Usage / Metering | Works partially | Plan, usage, auto-top-up render — but only as a Settings sub-tab, and not in the model you have now described |
| Integrations / Connectors | Works partially | Full catalogue at `/app/integrations`; `/integrations` returns 404. Instant revocation does not complete — see below |
| Ask BIQc / Soundboard | Works partially | Answers prompts correctly; no clean route of its own |
| Team & Governance | **Not ready** | Invite unreachable on the deployment; three backend endpoints do not exist |
| Manage users | **Not ready** | Sends the user to the billing screen and discards the request |
| Admin (non-admin handling) | **Not ready as specified** | Generic 404 instead of an explicit "access restricted" |
| BIQc Wallet | **Does not exist** | Newly confirmed scope; not present in code or API in any form |

## 5. What this team does well

A report of pure complaints is not a useful report, and these are decisions I would defend in review:

- When the backend reports a successful disconnect but removes nothing, **the UI refuses to show success** rather than lying to the user. A correct answer to open backend issue #1427.
- Where no member-list endpoint exists, the Team page shows an **explicit placeholder with a reason code** instead of inventing a fake list.
- Admin routes **re-check the role against the backend** rather than trusting what the UI displays. The subscription gate fails closed.
- A live test confirmed **signing out in one tab immediately closed a second privileged tab**, and billing data did not return via the browser's back button.
- A live probe confirmed **billing, team and admin actions do not execute without authentication** — the server rejects them; it does not rely on hidden buttons.
- **Code comments are dated and carry the reason plus PR number.** With 78% machine authorship this is an unusually valuable asset: intent is recoverable without archaeology.
- **The `frontend/` directory itself is clean** — ten files at its root, no backup copies, no stray `.bak` or `.orig`, consistent structure. The disorder in this project is at the repository root and in the process, not in the code Anjali wrote.
- **No secrets have leaked into the repository.** The variable registry is correctly written and contains names only, verified.

## 6. The end-of-week question

Your confirmed scope now includes multi-user, instant revocation from day one, and BIQc Wallet with credit purchase, per-user allocation and auto top-up.

Against roughly four working days, the position is:

- front-end blockers already identified: **64–128 hours**
- three backend endpoints required for multi-user — member list, revoke, remove — **do not exist**
- instant revocation is blocked by open backend issue **#1427**
- **Wallet has not been started** on either side, and cannot be built before multi-user works, because credits cannot be allocated to members who cannot be listed or invited

Most of that is backend work, concentrated on one developer, so it cannot be parallelised away.

Two honest paths, and the choice is yours:

**Path A — hold the date, cut the scope.** Ship a single-tenant Release 1: one account, one owner, no invitations, no Wallet. Reachable in a short window, because what stands in the way is drift and configuration rather than missing features. Multi-user and Wallet become Release 1.1 with a real date.

**Path B — hold the scope, move the date.** A multi-week programme dominated by backend work. A date cannot be set until Anjali has estimated the missing endpoints, #1427, and the Wallet ledger.

What I would avoid is deploying the announced scope on the announced date. The specific risks are not cosmetic: an invited user with nowhere to land, a revocation that reports success without revoking, and a credit balance whose behaviour under simultaneous spending has never been tested. The last one is money.

## 7. Cost

| Stage | Effort |
| --- | --- |
| Close `main` with branch protection and required checks | **2–3 hours** — do this regardless of which path you choose |
| Front-end P0 blockers (toolchain, build, routes, invite) | 64–128 hours |
| Invite acceptance route and landing surface | 12–20 hours |
| Wallet — front end only | 60–100 hours |
| Missing multi-user endpoints, #1427, Wallet backend | Backend scope — needs Anjali's estimate |
| Trustworthy long-term baseline (tests, lint gate, edge hardening) | 47–85 hours |
| Repository cleanup | 5–6 hours, Phase 2 |

I have deliberately not estimated backend items. Those are Anjali's to scope, and an outside number on work I have not examined would look authoritative and be invented.

## 8. What I am not proposing

Not a rewrite, not a framework migration, not a large refactor as part of Release 1. None of that is what stands between you and a defensible release decision.
