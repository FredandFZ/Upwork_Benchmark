# Evidence Log

What was executed, in what environment, and what it produced. Included so the findings can be re-run and challenged rather than taken on trust.

**Environments**
- Repository: `biqc-ai/Version2-Ai_Mentor`, private monorepo, read-only clone plus archive analysis including git history
- Deployment: `https://dev.biqc.ai/`, account `devteam.sandbox@biqctest.io`
- API surface for contract checks: `https://biqc-api-dev.azurewebsites.net/docs`
- No staging environment exists; dev and prod only

**Repository as observed:** 6,456 commits, 29 branches, 5 contributors, 26 open and 196 closed issues, 5 open and 1,308 closed PRs. Languages: Python 47%, JS 31%, PLpgSQL 8%.

**Front-end stack as observed:** CRA + CRACO, React 19.2.7, react-scripts 5.0.1, JavaScript without TypeScript, Tailwind + Radix UI (≈40 components, design tokens via CSS variables, `components.json`), Supabase auth, axios. 143,466 lines of JS/JSX, 96 pages, 151 routes, 170 test suites.

---

## Task log — code, build, runtime

| Task | What was done | Outcome | Findings |
| --- | --- | --- | --- |
| T-01 | Test run on clean checkout, Node 20 then Node 22 | Not runnable under Node 20; runnable under Node 22 | A-01 |
| T-02 | Full suite, `--runInBand` | 11 failed / 159 passed / 170 total; 23 failed / 1,640 passed / 1 skipped / 1,664 tests | A-02 |
| T-03a | Root-cause classification of the 11 red suites | 1 real code violation, 10 stale / contradictory / environmental | A-04 – A-10 |
| T-03b | Temporary ESLint profile, application code only | 2,775 problems (125 errors, 2,650 warnings); `rules-of-hooks` 0, `no-undef` 0 | A-11 |
| T-04 | Invitation flow — static then runtime | Static hypothesis **disproved**; runtime gap confirmed | A-12, A-23 |
| T-05 | Interval leak — static plus 15-cycle navigation stress | Hypothesis **not confirmed** | withdrawn |
| T-06 | Console output — static plus live browser console | Escalation criterion **not met** | withdrawn |
| T-07 | Production build | Fails to compile | A-13, A-26 |
| T-08 | Dependency override vs Dependabot | Override pins `1.8.4` | A-14 |
| T-09 | Dev walkthrough of every R1 module | Repeatable route drift confirmed | A-15, A-16, A-17 |
| T-10 | Deployed asset exposure and edge headers | Source-map exposure **not confirmed**; header posture weak | A-18, A-19, A-26 |
| T-11 | Cache/auth boundary across a logout/login cycle | No cache leak; fallback UX ambiguous | A-20 |
| T-12 | Stale privileged access across tabs after sign-out | No stale access; residual role-lag concern | A-21 |
| T-13 | Backend enforcement probe on billing / team / admin | Enforcement holds; invite contract drift found | A-22 |

## Task log — repository and process

| Task | Command | Result | Finding |
| --- | --- | --- | --- |
| H-a | `git log --format='%an' \| sort \| uniq -c \| sort -rn` | 5,057 of 6,456 commits by `emergent-agent-e1` (78.3%) | H-01 |
| H-b | Root `.gitconfig` inspection | Pins agent identity for the whole tree | H-01 |
| H-c | `find . -maxdepth 1 -type f -size -1c` | Nine zero-byte files plus `$null)` (101 B) | H-02 |
| H-d | `evidence*` directory enumeration | 7 directories, 16 files, 228 KB, one shared last commit | H-03 |
| H-e | `find . -maxdepth 1 -type f \| wc -l` / `ls *.md \| wc -l` / `ls \| grep -c "13041978"` | 82 / 24 / 17 | H-04 |
| H-f | Dockerfile enumeration and `diff` | Four files; `Dockerfile` and `Dockerfile.txt` diverge | H-05 |
| H-g | Cross-reference of `pages/` against routes in `App.js` | 8 modules unrouted, 4,674 lines | H-06 |
| H-h | Agent config and `.screenshots/` timestamps | `.emergent/` 4mo, `.claude/` 2mo, `.cursor/` 1mo | H-07 |
| H-i | `SECRETS_AND_DEPENDENCIES.md` value scan | Names only; no values present | H-08, H-09 |
| H-j | Junk-mask scan of `frontend/` | No `.bak` / `.orig` / `_old`; two benign matches | H-09 |

---

## Withdrawn hypotheses

Tested and removed. Documented rather than deleted, because knowing what was checked and cleared is part of the deliverable.

### W-1 · "The invite flow is absent from the front-end code" — **false**
The claim was that the invite endpoint is never called and no route exists in `App.js`. Disproved: `App.js:556` mounts `/team-access`, and `TeamAccessPage.js:154-158` performs a real invite POST rendering `invite_link`, `temp_password` and `expires_at` from the server. The real problem is narrower and different in kind — the deployment does not expose the surface. Carried forward as `A-12`. Note that the *acceptance* half of the flow is genuinely missing, which is `A-23`; the two should not be conflated.

### W-2 · "Production console logging may expose tokens or API responses" — **not confirmed**
`frontend/src/index.js:27-35` overrides `console.log`, `info`, `debug`, `warn` and `error` to no-ops in production. CRA does not strip `console.*`, but this codebase suppresses it at runtime. Active debug statements outside comments are limited to `index.js:30-32`, `lib/api.js:420`, `lib/analytics.js:89`, `lib/telemetry.js:84`, `hooks/useAlerts.js:108`; the first four are environment-guarded, and `lib/api.js:418-420` logs auth-state metadata and request path, not raw tokens. Live on dev: sign-out, re-login and an Ask BIQc submission produced only reCAPTCHA `net::ERR_ABORTED` noise and one `MaxListenersExceededWarning` from the automation tooling — no tokens, no session objects, no API payloads, no PII.

### W-3 · "Intervals leak in `useAlerts.js` and `Advisor.js`" — **not confirmed**
Every real `setInterval` has a matching `clearInterval` in the same `useEffect` cleanup: `useAlerts.js:118-124` (set `:122`, clear `:123`), `Advisor.js:222-228`, `:258-264`, `:332-338`. The original mismatch came from counting text — `useAlerts.js:39` and `Advisor.js:46` mention `setInterval` in comments only. The task also assumed 60-second polling; the source sets `POLL_INTERVAL_MS = 180_000` at `useAlerts.js:36`, and `DashboardLayout.js:182-213` shows `/notifications/alerts` now uses Supabase Realtime with `supabase.removeChannel(channel)` cleanup rather than polling. Runtime: 15 SPA cycles across `/` → `/app/integrations` → `/app/settings` (45 transitions), timings cleared, session held ~190 seconds — exactly **1** request to `/api/alerts/active` and **1** to `/api/notifications/alerts`. No amplification.

### W-4 · "CI runs 7 of 157 tests" — **restated**
The observable inventory is **170**, not 157. And the gap is not "150 tests are disconnected from CI"; it is a mix of CI under-selection (`A-03`), stale test inventory (`A-05`–`A-07`) and a small number of genuine code-level issues (`A-04`). Any coverage figure quoted from the earlier denominator must be restated.

---

## A note on numbering

Earlier working material used an `F-01`…`F-16` scheme predating the test runs. That scheme is superseded. Where earlier documents name `F-02`, `F-04` and `F-05` as the release blockers, read instead: `A-12` and `A-23` (team access — with the code-level half of `F-02` disproved), `A-25` (owner-facing credit and metering, now expanded into Wallet), and `A-02` / `A-03` (test gate, with the corrected denominator).

---

## Artefacts

Produced during the audit, available on request:

- `test-run.log`, `test-run-node22.log`, `test-run-node22-runinband.log`
- `eslint-report.json`, from the temporary uncommitted `frontend/eslint.config.js`
- Screenshots: `t09-settings-direct-blank.png`, `t09-app-settings.png`, `t09-team-access-404.png`, `t09-app-integrations.png`, `t09-integrations-direct-404.png`, `t09-soundboard-workspace-before-send.png`, `t09-manage-users-redirect-billing.png`, `t09-admin-404.png`
- Browser network logs from T-09 — four capture windows, 22:32–22:37 UTC, 26 July 2026
- The verification task list issued during the audit, supplied separately as a working journal
