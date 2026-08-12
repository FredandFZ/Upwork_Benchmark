# Technical Layer — Findings Register

Thirty-four findings in two parts:

- **Part A (`A-01`…`A-25`)** — code, build, deployment and runtime behaviour
- **Part B (`H-01`…`H-09`)** — repository organisation and delivery process

Severity is assigned by **release impact**, not code aesthetics. Confidence states how far the evidence goes: High = directly observed; Medium = strongly implied with a stated gap in the evidence chain.

Paths are relative to the repository root unless prefixed with a URL.

---

# Summary

| ID | Finding | Severity | Conf. | Hours |
| --- | --- | --- | --- | --- |
| **A-01** | Test workflow not reproducible from clean checkout under Node 20 | Critical | High | 8–16 |
| **A-02** | 11 of 170 local suites red, several covering R1 contracts | Critical | High | see A-04–A-10 |
| **A-03** | CI proves a narrow slice and uses a non-canonical install path | High | Medium | 8–12 |
| A-04 | Authenticated-route typography policy violated in live pages | Medium | High | 2–4 |
| A-05 | Red suites targeting deleted or decommissioned surfaces | High | High | 3–5 |
| A-06 | Red suites enforcing superseded product expectations | High | High | 6–10 |
| A-07 | Test layer contains mutually contradictory guards | High | High | 6–10 |
| A-08 | AskBiqc banned-token scan fails on a comment-only false positive | Medium | High | 1–2 |
| A-09 | Paid-feature copy-lock constants and tests have diverged | Medium | High | 2–3 |
| A-10 | One red suite is a Jest/router resolution issue | Medium | High | 1–2 |
| A-11 | No active lint gate; temporary profile finds 2,775 issues | High | High | 8–16 |
| **A-12** | Team invite exists in source but unreachable on the deployment | Critical | High | 12–24 |
| **A-13** | Production build fails before a valid optimized bundle | Critical | High | 8–24 |
| A-14 | `shell-quote` override pin makes the Dependabot bump inert | Low | High | 1 |
| **A-15** | Deployment route map does not match the R1 direct routes | Critical | High | 16–32 |
| **A-16** | Integrations and Ask BIQc reachable only via alternate surfaces | High | High | in A-15 |
| **A-17** | `manage-users` and `admin` fail access-control UX differently | High | High | 6–10 |
| A-18 | Edge serves report-only CSP permitting `'unsafe-inline'`; no HSTS | High | High | 6–12 |
| A-19 | Conflicting duplicate security headers across layers | Medium | High | 3–6 |
| A-20 | Protected-route fallback after logout is visually ambiguous | Medium | High | 3–6 |
| A-21 | Role-downgrade UX may lag backend truth | Medium | Medium | 4–8 |
| **A-22** | Live invite RBAC does not match the `{owner, admin}` contract | High | Medium | 4–8 |
| **A-23** | Multi-user chain incomplete: no accept route, no member endpoints | Critical | High | 12–20 FE |
| **A-24** | Instant revocation does not complete — blocked by backend #1427 | Critical | High | backend |
| **A-25** | BIQc Wallet does not exist in code or API | Critical | High | 60–100 FE |
| A-26 | Production source-map posture unverified | Medium | Medium | 1–2 |
| **H-01** | 78% of commits are agent-authored, merged with no branch protection | High | High | **2–3** |
| H-02 | Failed-shell-command artefacts committed to the root | Medium | High | 0.2 |
| H-03 | Seven `evidence*` directories holding 16 files | Medium | High | 1 |
| H-04 | 82 files at the repository root, 24 of them markdown | Medium | High | 2 |
| H-05 | Four Dockerfiles, two of which diverge | Low-Med | High | 1 |
| H-06 | 4,674 lines of unreachable front-end code | Medium | High | 1 |
| H-07 | Three AI agent configurations committed | Low | High | 0 |
| H-08 | Secrets registry in the repository (names only, no values) | Low | High | 0 |
| H-09 | What is organised well | — | — | — |

**Consolidated P0 front-end effort:** 64–128 hours for A-01/A-02/A-03/A-12/A-13/A-15/A-16/A-17/A-22, plus 12–20 for A-23 and 60–100 for A-25, with backend items unestimated. **H-01 at 2–3 hours has the highest ratio of leverage to cost in this register.**

---

# Part A — Code, build, deployment

## P0 — Release blockers

### A-01 · Test workflow is not reproducible from a clean checkout under Node 20
**Critical · High · 8–16h**

**Evidence**
- `frontend/package.json:37` pins `@supabase/supabase-js` to `^2.110.2`
- `frontend/node_modules/@supabase/supabase-js/package.json:112-114` requires `node >=22.0.0`
- `frontend/package.json:70-73` defines `craco test` as the standard entrypoint
- `test-run.log:1-2` — first run failed before Jest started (`npm error could not determine executable to run`)
- `yarn install --frozen-lockfile` under Node `v20.20.2` fails on the engine constraint
- Under Node `v22.14.0` the install completes and the runner starts (`test-run-node22.log:13204-13208`)

**R1 consequence.** The declared toolchain and the only working toolchain are different versions. A clean checkout is not test-runnable on the documented path, so no release gate depending on front-end tests can be reproduced by a second engineer or a clean CI runner.

**Remediation.** One supported Node version, reconciled with dependency engine constraints and the lockfile, documented in the repository, matched in CI.

### A-02 · Eleven of 170 local suites are red, several covering R1 contracts
**Critical · High · effort itemised in A-04–A-10**

`test-run-node22-runinband.log:13208-13213` — suites `11 failed, 159 passed, 170 total`; tests `23 failed, 1 skipped, 1640 passed, 1664 total`; post-run warning `Jest did not exit one second after the test run has completed.`

| Suite | Reason |
| --- | --- |
| `Integrations.ws7ConnectorTruth.test.jsx` | Missing connector card `data-testid="integration-card-arrow-flow"` |
| `filesAndDocuments.tabs.test.jsx` | OneDrive card renders error/loading instead of expected "not connected" copy |
| `releaseOneMandatorySurfaceTruth.test.jsx` | Connector registry does not match the `arrow-flow` contract token |
| `profileMenuContract.test.jsx` | Profile menu contract missing the `billing` item |
| `authRouteSerifGuard.test.jsx` | Product-serif usage in `CMOReportPage.js` and `Integrations.js` |
| `AskBiqc.bannedTokens.scan.test.js` | Banned token `Codex` in `AskBiqcEvidencePanel.js` |
| `paidFeatureFlags.test.js` | Verifying-copy contract drifted from expected wording |
| `UiTrustSprint.fakeDefaults.scan.test.js` | Forbidden `Unavailable` label still present in Integrations source |
| `BiqcLogoCard.brandSweep.test.jsx` | Referenced landing source file does not exist at the expected path |
| `billingSyncHistoryTruth.test.jsx` | Scans `src/pages/Pricing.js`, which does not exist |
| `TierNudge.test.jsx` | `react-router-dom` resolves a missing `react-router/dom` under Jest |

**R1 module test status:** `AskBiqc*` mostly green, one red · `ProtectedRoute*` green (4 suites) · `Settings*` green · `TeamAccess*` green · `Integrations*` 5 green / 1 red · `billing*` 5 green / 1 red.

**R1 consequence.** Two corrections to earlier working assumptions. The observable inventory is **170**, not 157, so any coverage claim must be restated. And the gap is not simply "tests exist but aren't wired into CI": ten of the eleven failures are stale, superseded or environmental, and one (`A-04`) is a real current-code violation. The release harm is that a red baseline of mixed provenance trains the team to ignore red.

### A-03 · CI proves only a narrow green slice and relies on a non-canonical install path
**High · Medium · 8–12h**

- `AGENTS.md` states the front end uses `yarn` and warns against npm
- `frontend/package.json:165` declares `packageManager: yarn@1.22.22`
- `.github/workflows/shell-regression-gate.yml:36-45` installs with `node-version: '20'` and `npm install --legacy-peer-deps`
- `.github/workflows/shell-regression-gate.yml:47-67` runs only 7 targeted suites

**R1 consequence.** Local guidance, declared package manager and CI install strategy have drifted apart. A green pipeline is therefore weak evidence for a release decision. Read together with `H-05` (four Dockerfiles, two divergent), the build contour as a whole is not reproducible.

### A-12 · Team invite exists in source but is unreachable on the dev deployment
**Critical · High · 12–24h**

> **Correction.** The original hypothesis — that the front end never calls the invite endpoint and has no route — is **false at the code level**. The code implements the invite. The failure is a deployment access gap.

**Source evidence (present)**
- `frontend/src/App.js:556` mounts `<Route path="/team-access" element={<ProtectedRoute><RouteErrorBoundary><TeamAccessPage /></RouteErrorBoundary></ProtectedRoute>} />`
- `frontend/src/pages/TeamAccessPage.js:154-158` performs `apiClient.post('/account/users/invite', { email, name, role })`
- `frontend/src/pages/TeamAccessPage.js:186-199` renders server fields `invite_link`, `temp_password`, `expires_at`
- `frontend/src/pages/Settings.js:1089` exposes `href: '/team-access'`

**Runtime evidence (unreachable)** — account `devteam.sandbox@biqctest.io`
- `https://dev.biqc.ai/team-access` → `404 Page not found`
- `https://dev.biqc.ai/settings` → `404 Page not found`
- Account menu navigates to `/app/settings`, where a `Team & governance` section is visible
- That screen shows a disabled control labelled exactly `Copy invite link (backend pending)`
- Clicking `Team & governance` returns to `https://dev.biqc.ai/`
- `/app/team-access` shows `Establishing secure connection...` then returns to `https://dev.biqc.ai/`

**Not observable because of the gap:** the `Your role` value, invite submission, the literal `invite_link`, its behaviour in a private window, email delivery. All must be re-tested on the release candidate.

**R1 consequence.** With multi-user confirmed in scope, this is a hard blocker on a named R1 module, and Wallet (`A-25`) sits on top of it.

### A-13 · Production build fails before a valid optimized bundle
**Critical · High · 8–24h**

- `Creating an optimized production build...` → `Failed to compile.`
- `Error: [BABEL] ... React Refresh Babel transform should only be enabled in development environment. Instead, the environment is: "production"`
- Config area: `frontend/craco.config.js:5-22` and `:73-78`
- Post-failure `build/` is `1.7M`; `build/static/js/` holds only `bundle.js` (4.1K) and `bundle.js.map` (634B)

**R1 consequence.** No trustworthy production artefact exists. The `build/` directory is misleading — leftovers from an aborted compile. Three questions stay unanswerable until it passes: true main-chunk size, whether the 98 `lazy()` route splits in `App.js` survive into emitted chunks, and the final source-map posture (`A-26`).

### A-15 · Deployment route map does not match the expected R1 direct routes
**Critical · High · 16–32h**

- `https://dev.biqc.ai/settings` → broken direct route (`t09-settings-direct-blank.png`)
- `https://dev.biqc.ai/team-access` → 404 (`t09-team-access-404.png`)
- `https://dev.biqc.ai/integrations` → 404 (`t09-integrations-direct-404.png`)
- `https://dev.biqc.ai/soundboard` → resolves into `https://dev.biqc.ai/`
- The live app uses an `/app/...` route shape not reflected in the inspected source routes

**R1 consequence.** A live deployment fact, not a code-style inconsistency. QA cannot validate a contract the environment does not honour, and sign-off is ambiguous when the environment does not match the promised navigation model. Requires deployment ownership, not front end alone.

### A-16 · Integrations and Ask BIQc are usable only through alternate surfaces
**High · High · covered by A-15**

- `/app/integrations` renders a live connector catalogue after a bootstrap delay (`t09-app-integrations.png`)
- `https://dev.biqc.ai/` renders the Ask BIQc workspace and accepts prompts (`t09-soundboard-workspace-before-send.png`)
- The answer returned: `I can't provide a decision-safe recommendation yet because your core evidence lanes are stale or unproven.`
- Evidence drawer exposed `No connector evidence for this answer` and `Not connected ( 9 )`

The refusal to answer without grounded evidence is the product working as designed and is a positive signal. The negative is access pattern: indirect shells are fragile for QA, onboarding and demo.

### A-17 · `manage-users` and `admin` fail their access-control experience differently
**High · High · 6–10h**

- `/manage-users?view=users` ends at `/app/settings?tab=billing`; the `view=users` context is silently lost (`t09-manage-users-redirect-billing.png`)
- `/admin` under a non-admin account returns a generic 404 instead of `Access restricted` (`t09-admin-404.png`)

One route loses its destination and lands somewhere commercially sensitive; the other cannot distinguish "denied" from "missing" from "misrouted". Confusing for users, unusable for QA.

### A-22 · Live invite RBAC does not match the `{owner, admin}` contract in source
**High · Medium · 4–8h front end; backend effort separate**

Account role via live login API: `role: user_admin`, `subscription_tier: starter`, `subscription_status: active`.

| Endpoint | No auth | Valid `user_admin` bearer |
| --- | --- | --- |
| `POST /api/billing/portal` | `401 Not authenticated` | `200` with Stripe portal URL |
| `POST /api/account/users/invite` | `401 Not authenticated` | `403 User seats are not available for this plan tier` |
| `PUT /api/admin/ux-feedback/checkpoints` | `401 Not authenticated` | `403` structured admin/subscription denial |

**Source contract**
- `frontend/src/pages/TeamAccessPage.js:4-13` documents the endpoint as owner/admin-gated
- `frontend/src/pages/TeamAccessPage.js:26-31` defines `INVITE_ALLOWED_ROLES = ['owner', 'admin']`
- `backend/routes/deps.py:925-929` defines `require_owner_or_admin` as an exact match on `{owner, admin}`
- `backend/routes/onboarding.py:195-203` wires the endpoint through `Depends(require_owner_or_admin)` before seat checks

**R1 consequence.** Not unauthenticated mutation — runtime contract or role-normalisation drift. A `user_admin` bearer reached seat-tier enforcement instead of failing on the documented gate. Client-visible RBAC messaging and server enforcement are not provably aligned, on the one module whose entire purpose is access control. Confidence is Medium because the probe used a fresh valid bearer rather than byte-for-byte replay of the browser's post-logout token.

### A-23 · The multi-user chain is incomplete beyond the invite surface
**Critical · High · 12–20h front end; backend scope separate**

Confirmed in scope by the product owner on 27 July.

- The front end never calls `POST /account/users/accept`, and no route exists for an invited user to land on — verified in `App.js`
- **Member-list, revoke and remove endpoints do not exist** on the backend today
- The Team page states this honestly rather than faking it, with reason code `NO_BACKEND_LIST_ENDPOINT` (`frontend/src/pages/TeamAccessPage.js:490-505`)

**R1 consequence.** An invited user has nowhere to land, and an account owner cannot see, revoke or remove members. Combined with `A-12` and `A-22`, the team-access chain has four separate breaks, three of which are backend work that has not started.

### A-24 · Instant revocation does not complete — blocked by backend #1427
**Critical · High · backend scope**

Confirmed as a day-one requirement by the product owner on 27 July.

With #1427 open, the disconnect endpoints return success without removing the connection record. The front end handles this correctly and refuses to display success (`frontend/src/pages/Integrations.js:1088-1101`), so the user-visible outcome is that revocation does not complete.

**R1 consequence.** Either #1427 is fixed before launch, or the instant-revocation claim is removed from the product description until it is. Shipping the claim while the issue is open puts the marketing statement and system behaviour in conflict on a security-adjacent capability.

### A-25 · BIQc Wallet does not exist in code or API
**Critical · High · 60–100h front end; backend scope substantial**

Introduced as R1 scope by the product owner on 27 July: purchase of credit by Governance/Admin, allocation of credits to particular users, auto top-up.

What exists today: per-member token consumption, usage breakdown and individual limits in `pages/AdminDashboard.js` under `adminOnly` — the platform superadmin console. The account owner has access to none of it.

What Wallet requires and does not exist anywhere: an account-level credit balance with a purchase path; allocation from that balance to individual members; per-member balance enforcement at consumption time; auto top-up rules, thresholds and billing events; Governance/Admin authorisation over all of it; an audit trail for allocation and spend.

**Hard dependency.** Credits cannot be allocated to members while the member list does not exist (`A-23`), the invite path is unreachable (`A-12`) and invite role behaviour does not match its contract (`A-22`). The order is fixed.

**Highest-risk item in the register**, because it touches money. A credit ledger with allocation and auto top-up must behave correctly under concurrency: two members spending against one balance, a top-up landing during consumption, a limit boundary hit by simultaneous requests. Those failure modes produce direct revenue loss or customer-visible billing errors, and they are not safely built in days.

## P1 — Material, not launch-blocking

### A-04 · Authenticated-route typography policy violated in live pages
**Medium · High · 2–4h**
Policy at `frontend/src/__tests__/authRouteSerifGuard.test.jsx:4-9`, scan at `:31-40` (looks for `var(--font-display)`). Violations: `frontend/src/pages/CMOReportPage.js:54`, `:167`, `:490`; `frontend/src/pages/Integrations.js:1707`. The one red suite mapping cleanly to a real code violation. Fix the usages or formally retire the policy — do not leave the guard red.

### A-05 · Red suites targeting deleted or decommissioned surfaces
**High · High · 3–5h**
- `billingSyncHistoryTruth.test.jsx:29-35` still scans `pages/Pricing.js`
- `Pricing.tokenWording.test.js:7-12` explicitly documents that `pages/Pricing.js` was deleted
- `frontend/src/App.js:425-430` shows `/pricing` and marketing pages now redirect to static pages
- `BiqcLogoCard.brandSweep.test.jsx:45-49` still points to `frontend/src/pages/website/HomePage.js`
- `frontend/src/App.js:421-430` and `:456` show the current model no longer matches that target

### A-06 · Red suites enforcing superseded product expectations
**High · High · 6–10h**

*Billing navigation* — `profileMenuContract.test.jsx:19-24` expects `billing` in `SHELL_PROFILE_MENU`; `frontend/src/components/shell/shellNav.js:142-146` states Billing was removed from the account menu and now lives only in Settings; `App.js:540-541` redirects `/billing` → `/settings?tab=billing`; `docs/release1-command-inventory/10_PAGE_PURPOSE_AND_FOUNDER_INTENT_MATRIX.md:1530-1540` describes a single billing surface.

*Integrations request-access* — `releaseOneMandatorySurfaceTruth.test.jsx:36-59` and `Integrations.ws7ConnectorTruth.test.jsx:203-229` expect `arrow-flow`; `frontend/src/pages/Integrations.js:309-317` shows `REQUEST_ACCESS_CONNECTORS` is empty; `docs/...MATRIX.md:1273-1285` documents the array as intentionally empty with repopulation optional; `:1257-1268` shows R1 emphasis on native connectors (Mindbody, AroFlo, Zapier).

*Files & Documents* — `filesAndDocuments.tabs.test.jsx:269-276` expects the OneDrive card to always read as not connected; `frontend/src/pages/FilesAndDocuments.js:17-19` defines the contract as explicit retryable error states, never fake empty states; `:232-258` sets an `error` phase on failed fetch; `:639-646` renders the retryable state.

### A-07 · The test layer contains mutually contradictory guards
**High · High · 6–10h**

*Arrow Flow* — `Integrations.nativeConnectorsAvailability.test.js:38-45` expects `arrow-flow` **not** to exist; `releaseOneMandatorySurfaceTruth.test.jsx:36-59` and `Integrations.ws7ConnectorTruth.test.jsx:203-229` expect it to exist.

*`Unavailable` label* — `UiTrustSprint.fakeDefaults.scan.test.js:153-165` forbids it and requires `Coming soon`; `Integrations.connectionVerificationTruth.test.jsx:23-27` requires it in verification-state logic; source at `frontend/src/pages/Integrations.js:1945-1946`, `:2014-2015`.

These cannot all pass. Where tests contradict each other, pass/fail stops indicating product truth.

### A-08 · AskBiqc banned-token scan fails on a comment-only false positive
**Medium · High · 1–2h**
`AskBiqc.bannedTokens.scan.test.js:41-51` defines the allowlist; `frontend/src/components/askBiqc/panels/AskBiqcEvidencePanel.js:209` is the only hit, in comment text, not rendered. Worth fixing precisely because false positives on useful customer-safety guards teach the team to ignore them.

### A-09 · Paid-feature copy-lock constants and tests have diverged
**Medium · High · 2–3h**
`frontend/src/config/paidFeatureFlags.js:63-68` documents older "being verified" wording; `:149-162` exports newer "temporarily unavailable" constants; `paidFeatureFlags.test.js:81-93` still expects the older; `frontend/src/components/soundboard/DrivePickerLandingPill.js:94` already uses the newer.

### A-10 · One red suite is a Jest/router resolution issue
**Medium · High · 1–2h**
`TierNudge.test.jsx:1-3` imports real `MemoryRouter`; `frontend/src/components/TierNudge.js:28` imports `Link`; failure is `Cannot find module 'react-router/dom' from 'react-router-dom/dist/index.js'`. Other suites already mock `react-router-dom` — e.g. `Integrations.ws7ConnectorTruth.test.jsx:21-29`.

### A-11 · No active lint gate; a minimal profile finds 2,775 issues
**High · High · 8–16h for a changed-files gate**

Instrument: a temporary local `frontend/eslint.config.js`, **not committed**, scoped to application code by ignoring nested `__tests__`, nested `tests`, root `*.test.js(x)` and `src/setupTests.js`. Output `eslint-report.json`.

- Total `2775` — `125` errors, `2650` warnings
- `no-unused-vars` 2595 · `no-empty` 102 · `parse/unknown` 33 · `react-hooks/exhaustive-deps` 24 · `no-useless-assignment` 10 · `no-dupe-keys` 5
- `react-hooks/rules-of-hooks`: **0** · `no-undef`: **0**

`exhaustive-deps` locations: `components/DashboardLayout.js:239`, `components/IntelligenceSimulation.js:16`, `:27`, `components/VoiceChat.js:497`, `components/business-dna/KpiThresholdTab.js:71`, `components/soundboard/AskBiqcAssistantResponse.js:284`, `components/soundboard/AskBiqcWorkActivity.js:152`, `components/website/LiquidSteelHeroRotator.js:106`, `hooks/useSWR.js:56`, `pages/AdminDashboard.js:646`, `pages/Advisor.js:398`, `:701`, `pages/AdvisorWatchtower.js:1082`, `:1603`, `pages/BusinessProfile.js:58`, `pages/CompliancePage.js:146`, `pages/Diagnosis.js:189`, `pages/EmailInbox.js:212`, `pages/Integrations.js:851`, `:965`, `:1030`, `pages/OnboardingWizard.js:92`, `:172`, `pages/Settings.js:750`

Top files: `App.js` 133 (2 err) · `CMOReportPage.js` 54 · `AdvisorWatchtower.js` 47 (8 err) · `DataCenter.js` 45 · `RiskPage.js` 45 · `Settings.js` 45 · `MarketPage.js` 43 · `SoundboardPanel.js` 41 · `RevenuePage.js` 41 · `AdminDashboard.js` 40 (13 err)

**Interpretation.** The number that matters is not 2,775 — that is dominated by unused variables, i.e. drift under shipping pressure. The two that matter are `rules-of-hooks: 0` and `no-undef: 0`: this is not a codebase full of latent runtime crashes. Recommendation is a gate on changed files, not a cleanup campaign before R1. Note also that `AdvisorWatchtower.js`, third by violation count, is unreachable code (`H-06`).

### A-18 · Edge does not enforce CSP and permits inline script in policy
**High · High · 6–12h**
`curl -sI https://dev.biqc.ai/` returns `content-security-policy-report-only`, not `content-security-policy`; the policy includes `script-src 'self' 'unsafe-inline' https:`; `curl -s https://dev.biqc.ai/` shows multiple inline `<script>` blocks; no `strict-transport-security` on the front-end root. Not proof of an XSS bug — a hardening gap. Report-only does not block injected script.

### A-19 · Conflicting duplicate security headers across layers
**Medium · High · 3–6h**
`GET https://dev.biqc.ai/api/auth/supabase/me` returned `x-frame-options: DENY` **and** `SAMEORIGIN`; `x-xss-protection: 1; mode=block` **and** `0`; `referrer-policy` twice; two different `permissions-policy` values; and a strict backend CSP (`default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`) mixed with the looser front-end report-only policy. Multiple layers injecting independently makes the effective policy unpredictable, on authentication endpoints where predictability matters most.

### A-20 · Protected-route fallback after logout is visually ambiguous
**Medium · High · 3–6h**
Cache headers were correct throughout (`no-cache, no-store, must-revalidate` on `/` and `/app/settings`; `no-store, must-revalidate, no-cache, max-age=0` on `/api/auth/supabase/me`). After Sign Out, back-navigation did not restore billing content, and logged-out navigation to `/app/settings?tab=billing` did not restore account data. The residual issue is presentation: it resolves to the root login modal over a generic shell rather than a clean auth redirect — the same route-contract drift as `A-15`, expressed at the auth boundary.

### A-21 · Role-downgrade UX may lag backend truth
**Medium · Medium · 4–8h**
`frontend/src/pages/Settings.js:655-663` computes billing-control visibility from `canManageBilling(user)`; `frontend/src/lib/privilegedUser.js:61-92` makes that a client-side decision on in-memory `user.role`; `frontend/src/context/SupabaseAuthContext.js:316-379` preserves enriched fields until `/auth/supabase/me` refreshes; `frontend/src/components/ProtectedRoute.js:141-163` re-checks admin access against the backend. The tested scenario was clean. Residual risk is briefly stale controls after a mid-session downgrade — "visible but denied", not privilege retained. Not executable in audit mode without server-side role mutation.

### A-14 · `shell-quote` override pin makes the Dependabot bump inert
**Low · High · 1h**
`frontend/package.json:159` sets `"shell-quote": "1.8.4"` in `overrides`; `frontend/yarn.lock:10809-10812` resolves both `^1.7.3` and `^1.8.4` to `1.8.4`. An automated PR raising a transitive range will not move the installed version while the override stands. *Limitation:* `yarn why` was not executed in audit mode, so this rests on the manifest and lockfile.

### A-26 · Production source-map posture unverified
**Medium · Medium · 1–2h once A-13 is fixed**
A `.map` was emitted during the failed build and no config visibly disables source maps for production. On the deployment the exposure was **not** confirmed: `https://dev.biqc.ai/static/js/main.beeb0f42.js` was retrievable but exposed no `sourceMappingURL` trailer, and both `.map` URLs returned HTML rather than a source-map payload. Carry as an open build-pipeline question, not a confirmed exposure.

---

# Part B — Repository organisation and process

Method: static analysis of the `Version2-Ai_Mentor` archive including git history. Every figure is reproducible with the command shown.

**A distinction to hold throughout this part.** The `frontend/` directory itself is tidy: ten files at its root, no backup copies, no `.bak` or `.orig`, a coherent `pages` / `components` / `hooks` / `lib` / `context` structure. The disorder is at the repository root and in the process, not in the code the developer wrote. This part is about project organisation, not about anyone's craft.

### H-01 · 78% of commits are agent-authored and merged without branch protection
**High (process) · High · 2–3h**

```bash
git log --format='%an' | sort | uniq -c | sort -rn
```

| Author | Commits | Share |
| --- | --- | --- |
| `emergent-agent-e1` | 5,057 | 78.3% |
| `andrealexopoulos-star` | 1,229 | 19.0% |
| `dependabot[bot]` | 61 | 0.9% |
| `Andreas Alexopoulos` | 51 | 0.8% |
| `BIQc.ai` | 43 | 0.7% |
| `Cursor Agent` | 7 | — |
| `aikido-autofix[bot]` | 4 | — |
| `Claude Fable 5` | 3 | — |
| `Claude` | 1 | — |

Total 6,456 commits. A `.gitconfig` committed at the repository root fixes agent identity for anyone working in the tree:

```
[user]
	email = github@emergent.sh
	name = emergent-agent-e1
```

What follows from the facts: the developer does not appear in the commit history under her own name at any point, and which commits are hers cannot be determined from the archive; the second-largest author by volume is the product owner, not a developer; and the committed `.gitconfig` means authorship of any commit from this tree defaults to the agent regardless of who did the work.

**R1 consequence.** "Vibe coding" in the developer's own description is not a figure of speech but a measurable property: four commits in five are machine-made. That changes what review means. With 1,308 closed PRs and no branch protection, the question "what exactly is in production" has no answer available to a human. This is also what open issue #1533 — *Governance leftovers: branch protection* — is pointing at.

**What it does not mean.** Machine authorship does not make code bad. The `lib/api.js` layer examined earlier (642 lines, in-flight GET de-duplication, single-flight token refresh, per-URL cooldown) is competently written. The problem is not the origin of the code; it is the absence of a gate between it and production.

**Remediation.** Branch protection on `main`, required review, required status check — 2–3 hours. Remove `.gitconfig` from the repository — 5 minutes. **This is the highest-leverage item in the entire register.**

### H-02 · Artefacts of failed shell commands committed to the root
**Medium · High · 10 minutes**

```bash
find . -maxdepth 1 -type f -size -1c
```

Nine zero-byte files named `page`, `signal`, `decision`, `login`, `onboarding`, `Account`, `Observe`, `Refine`, `2%`. Plus a 101-byte file named `$null)` containing:

```
'$AZURE_CREDS' is not recognized as an internal or external command,
operable program or batch file.
```

The mechanism is legible: commands were run in a Windows shell, redirection behaved differently than intended, and files were created from fragments of a variable name. The error message landed in `$null)` and was committed with the rest.

**R1 consequence.** No direct technical harm. It is an indicator: between "the command did the wrong thing" and "the result is in `main`" there is no person and no check. The same gap passes substantive errors.

Separately: `$AZURE_CREDS` is the *name* of an Azure credentials variable. No value is present in the file. No leak occurred.

### H-03 · Seven `evidence*` directories holding 16 files
**Medium · High · 1h, Phase 2**

| Directory | Files | Size |
| --- | --- | --- |
| `evidence/` | 1 | 12 KB |
| `evidence_f14/` | 3 | 40 KB |
| `evidence_f15/` | 1 | 12 KB |
| `evidence_f16/` | 1 | 12 KB |
| `evidence_r2b/` | 4 | 40 KB |
| `evidence_r2d/` | 1 | 24 KB |
| `evidence_r2e/` | 5 | 88 KB |

Seven top-level directories, 16 files, 228 KB, all sharing one last commit — `fix(p0-marjo): 23-branch integration — zero-401 + Contra…` — two months ago. The suffixes are explained nowhere in the repository.

**R1 consequence.** Verification artefacts are stored alongside source with no index and no expiry rule. A new joiner cannot distinguish a current proof from last quarter's. Consolidate into `docs/evidence/` with dates.

### H-04 · 82 files at the repository root, 24 of them markdown
**Medium · High · 2h, Phase 2**

```bash
find . -maxdepth 1 -type f | wc -l   # 82
ls *.md | wc -l                      # 24
ls | grep -c "13041978"              # 17
```

Seventeen files carry the same numeric suffix `13041978` — `AI_MODELS_VENDOR_RELEASE_INVENTORY_13041978.md`, `CURSOR_BACKEND_ENVIRONMENT_REMEDIATION_REGISTER_13041978.md`, `CURSOR_GITHUB_RELEASE_GATES_REGISTER_13041978.md`, `CURSOR_STRIPE_TOPUP_WEBHOOK_REGISTER_13041978.md`, `CURSOR_SUPABASE_DRIFT_RECONCILIATION_13041978.md`, `REPO_48HR_CONSOLIDATION_LOCK_13041978.md` and others. The same number appears in the `deploy/` commit message: `[13041978][website-approved] promote wave 2: Ask BIQc…`. It is a session or consolidation-wave identifier, explained nowhere.

Also at the root: seven PNG screenshots (`advisor-forensic-1366x768.png` and resolution variants), `BIQc_Full_Stack_Audit.docx`, four Dockerfiles, and a single TypeScript file `OUTLOOK_AUTH_FIXED.ts` (6.2 KB) — while `frontend/src` contains no `.ts` at all. In parallel there are `docs/` (160 files) and `reports/` (90 files).

**R1 consequence.** There is a great deal of documentation and no single home or recency signal for it. With 250+ documents across three locations, the probability that someone reads a superseded one is close to certain. This has a direct cost: a contractor spends billable hours establishing which document is current.

### H-05 · Four Dockerfiles, two of which diverge
**Low-Medium · High · 1h**

```
Dockerfile             981 bytes
Dockerfile.backend     872 bytes
Dockerfile.frontend  14,508 bytes
Dockerfile.txt       1,125 bytes
```

`Dockerfile` and `Dockerfile.txt` differ in content (`diff` is non-empty). Which is used at build time cannot be established from the archive; `Dockerfile.txt` will not be picked up by any standard tool with that extension, so it is either a just-in-case copy or a forgotten older version. `Dockerfile.frontend` at 14.5 KB is very large — a typical front-end image fits in 30–60 lines.

**R1 consequence.** Ambiguity about what is actually built and deployed. Combined with `A-03` (CI installs via `npm install --legacy-peer-deps` against a canonical `yarn.lock`), the build contour is not reproducible.

**To check by hand:** which Dockerfile the dev deployment pipeline references.

### H-06 · 4,674 lines of unreachable front-end code
**Medium · High · 1h**

Eight modules in `pages/` are not wired into the router in `App.js`:

| File | Lines | Status |
| --- | --- | --- |
| `pages/AdvisorWatchtower.js` | 2,605 | Not routed; `/watchtower` goes to `components/Watchtower` |
| `pages/BillingPage.js` | 826 | Decommissioned |
| `pages/TermsAndConditions.js` | 432 | Superseded by static `trust-terms.html` |
| `pages/BIQcFoundationPage.js` | 200 | Not referenced anywhere |
| `pages/AuthDebug.js` | 176 | Debug page |
| `pages/MoreFeaturesPage.js` | 175 | Not referenced anywhere |
| `pages/TrustPage.js` | 151 | Superseded by static `trust.html` |
| `pages/OutlookTest.js` | 109 | Test page |

Total 4,674 lines — 3.3% of the front end.

Two qualifications, so the finding is not overstated:

1. `TrustPage` and `TermsAndConditions` are **not a compliance gap**. The routes `/trust`, `/trust/terms`, `/trust/privacy`, `/trust/dpa`, `/trust/security` are served (`App.js:434-438`) through `StaticMarketingRedirect` to static HTML. The React versions are migration residue.
2. `AdvisorWatchtower.js` is the largest file in the codebase and unreachable — **yet a live test guards it**: `__tests__/p0_7_polling_and_auth_state.test.js:412` checks it for a FULL_AUTH gate, and line 453 includes it in the file list under that rule. The test suite is protecting dead code.

**R1 consequence.** `AuthDebug.js` and `OutlookTest.js` are debug pages in a production repository. They are not mounted today, but one line in `App.js` exposes a debug surface. The rest costs navigation time: a developer looking for billing or watchtower will likely open the wrong file.

**Before deleting `AdvisorWatchtower.js`, confirm with the developer whether it is planned to return in R1.** 2,605 lines should not be discarded without that answer.

### H-07 · Three AI agent configurations committed
**Low (observation) · High · 0h**

`.claude/` (2 files), `.cursor/` (4 files), `.emergent/` (2 files), plus `AGENTS.md` at the root. Last modified 2, 1 and 4 months ago respectively — the sequence tracks a change of tooling. Also `.screenshots/` (4 months), same origin, with automatic commits of the form `auto-commit for d0e7a82f-...`.

**R1 consequence.** None directly. It corroborates `H-01` from an independent source and explains stylistic heterogeneity across the codebase: different parts were written by different agents under different instructions. That matters for Phase 2 estimation — there is no single house style to extrapolate from.

### H-08 · Secrets registry in the repository — names only, no values
**Low · High · 0h**

`SECRETS_AND_DEPENDENCIES.md` at the root, marked "Last updated: 23 March 2026". Correctly built: it states explicitly that it holds no values, and lists only variable names and purposes (`OPENAI_API_KEY=`, `SUPABASE_*`, and so on by provider). Verified — no values present.

The only thing disclosed is the Supabase project identifier (`uxyqpdfftxpkzeppqtvk`) in a dashboard link. The project ref is already present in the client bundle, so this is not new exposure.

**R1 consequence.** The file is useful and correctly made. One caveat: it provides a complete map of external dependencies and integration points. Fine in a private repository; worth revisiting if access widens. Last updated four months ago; currency not verified.

### H-09 · What is organised well

A section on disorder is obliged to name the opposite, or it reads as fault-finding.

1. **`frontend/` is clean.** Ten files at its root, no backups, no `.orig` / `.bak` / `_old`. The only two matches against a junk mask are `biqc-agent-mascot-new.png` (a legitimate asset) and `BoardroomCouncilCard.copy.test.jsx` (a test). `src/` structure is consistent: `pages`, `components`, `components/ui`, `hooks`, `lib`, `context`, `config`, `__tests__`.
2. **`.gitignore` is considered**, with an explicit `# Secrets` section covering `*token.json*` and `*credentials.json*`.
3. **No secrets reached the repository.** Verified across the variable registry and the failed-command artefacts.
4. **Code comments are dated and carry the reason.** In `ProtectedRoute.js`, `App.js`, `TeamAccessPage.js`, edits carry PR numbers and an explanation of the decision. At 78% machine authorship this is an unusually valuable asset: intent is recoverable without digging through history.
5. **Dead code is marked, not hidden.** `App.js:118` documents outright that the `BillingPage` import was removed and the route decommissioned. The author did not leave a silent trap.

---

# Positive findings — Part A

Load-bearing for the credibility of this report; should survive summarisation.

| Observation | Evidence |
| --- | --- |
| UI refuses to claim a successful disconnect when the backend returns `200` with `deleted_count === 0` — a correct answer to open issue #1427 | `frontend/src/pages/Integrations.js:1088-1101` |
| Explicit placeholder with reason code `NO_BACKEND_LIST_ENDPOINT` instead of a fabricated member list | `frontend/src/pages/TeamAccessPage.js:490-505` |
| Admin routes re-check role against the backend; subscription gate fails closed; dev bypass requires `NODE_ENV=development` | `frontend/src/components/ProtectedRoute.js` |
| Auth invalidation clears local state on `onAuthInvalidated()` and terminal signed-out paths | `frontend/src/context/SupabaseAuthContext.js:141-160`, `:248-298` |
| Client auth storage cleared and invalidation emitted on `401` from identity endpoints | `frontend/src/lib/api.js:486-494` |
| Cross-tab sign-out propagated correctly; second privileged tab lost billing access immediately | T-12 runtime |
| Unauthenticated billing, invite and admin mutations all rejected `401` | T-13 runtime |
| Cross-origin `GET` with `Origin: https://evil.example` returned no `Access-Control-Allow-Origin`; `OPTIONS` preflight returned `400` | T-10 runtime |
| Purpose-built API layer: in-flight GET de-duplication, single-flight token refresh, per-URL 401/403 cooldown, 402 handling | `frontend/src/lib/api.js`, 642 lines |
| Route-level code splitting implemented — 98 `lazy()` imports | `frontend/src/App.js` |
| Ask BIQc declines to give a decision-safe answer without grounded evidence, and says so | T-09 runtime |
| 159 of 170 suites pass once the environment is runnable | T-02 |
