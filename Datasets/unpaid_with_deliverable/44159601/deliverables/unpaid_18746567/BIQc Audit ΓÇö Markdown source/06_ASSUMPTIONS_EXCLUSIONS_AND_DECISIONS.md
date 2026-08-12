# Assumptions, Exclusions and Open Questions

---

## Assumptions

1. Release 1 is judged against the modules the team described as sufficiently built or close to lock — Authentication, Sidebar, Settings, Connectors, Ask BIQc, Billing & Usage, Team & Governance, Billing/Metering — extended by the product owner's confirmation of 27 July to include multi-user, instant revocation and BIQc Wallet.
2. Billing & Usage and Billing/Metering are one system, not two. Confirmed with the team.
3. Authentication was described as ready. It is reviewed anyway, because the invitation flow sits inside it and Team & Governance, per-member metering and Wallet all depend on that flow.
4. `dev.biqc.ai` is intended to be a meaningful pre-release validation environment. If it is not — if it is a scratch environment nobody expects to match the repository — several findings change character from release blocker to environment noise, and I would want to know that before you act on this report.
5. The repository state and the deployment are close enough that observed drift is a genuine release concern rather than a comparison of two unrelated snapshots.
6. Backend behaviour is considered only where it materially affects front-end release confidence.
7. Effort estimates assume one focused front-end engineer with availability from deployment and backend auth owners.
8. Commit-authorship figures reflect recorded git metadata. Because a committed `.gitconfig` fixes agent identity for the whole tree (`H-01`), recorded authorship is not a reliable indicator of who performed any individual piece of work, and no finding in this pack rests on attributing work to a person.

## Constraints on this audit

Stated so the gaps are visible rather than implied:

- **No staging environment exists.** Dev and prod only. There was no release-candidate contour to test against, so every runtime observation comes from dev.
- **The Release 1 route list was requested twice and not provided.** Only a module list was available. Route expectations are reconstructed from that list, from `App.js`, and from the repository's own `docs/release1-command-inventory/` material. If an authoritative list exists, `A-15` should be re-checked against it.
- **Figma was not received.** The link provided was a default Figma tutorial template with no project material. No design-conformance assessment was possible.
- **Swagger is weakly structured** — roughly 450 endpoints, four tags, almost everything under `default`, no versioning. Contract checks were targeted rather than exhaustive.
- **Audit mode: no state mutation.** Not executed: the Settings account-save mutation, connector disconnect-and-reload persistence (no connected connector existed on the audit account), invite submission, and any server-side role change needed to test role downgrade directly.
- **Token replay after logout was not possible.** The automation layer did not expose the browser's post-logout bearer, so `A-22` used a fresh valid bearer for the same account. Hence its Medium confidence.
- **Which Dockerfile is authoritative could not be established from the archive** (`H-05`). It requires access to the deployment pipeline configuration.
- **`yarn why shell-quote` was not executed** in audit mode, so `A-14` rests on the manifest and lockfile rather than a live resolver trace.

## Explicit exclusions

- No source code was changed. No fixes, no refactoring.
- No database changes or migrations.
- No full backend security audit. The backend was inspected only where it defines a contract the front end depends on.
- No load, stress or performance benchmarking. Bundle-size and code-splitting assessment was blocked by the failed production build (`A-13`) and remains open.
- No mobile-app readiness assessment.
- No production environment access and no validation of a production release artefact.
- No penetration testing. Security findings are configuration and posture observations, not exploitation attempts.
- No assessment of any individual's work quality. Commit volume and PR history are treated as process observations (`H-01`), and the register states explicitly where machine authorship does *not* imply poor code.
- No estimate of backend effort for the missing multi-user endpoints, #1427, or the Wallet ledger. Those belong to the developer who will build them.

## Questions answered on 27 July

1. **Is multi-user in Release 1?** — Yes. See `A-12`, `A-22`, `A-23`.
2. **Is instant revocation required from day one?** — Yes. See `A-24`.
3. **Was an owner-facing metering view planned?** — Superseded by the BIQc Wallet requirement. See `A-25`.

## Decisions for the team

These are not requests for information back to this audit. They are questions the audit surfaced that only the team can answer, listed with the consequence of leaving each one open. The findings and remediation estimates in this pack stand without them.

**On Wallet — these decide the data model and cannot be deferred past the start of the build**

1. Who may purchase credit — Governance and Admin both, or Owner only? Does purchase authority differ from allocation authority?
2. Is allocated credit reclaimable from a member, and what happens to unspent allocation when a member is removed?
3. What happens when a member's allocation runs out mid-request — hard stop, fall back to the account pool, or queue?
4. What triggers auto top-up, what caps it, and who is notified? An uncapped automatic purchase path is a commercial risk in its own right.
5. Is per-member spend an audit requirement — that is, must the system be able to show who spent what, after the fact?

**On the repository**

6. Is `AdvisorWatchtower.js` (2,605 lines, currently unreachable but guarded by a live test) planned to return in R1? It should not be deleted without this answer (`H-06`).
7. Which of the four Dockerfiles does the deployment pipeline use (`H-05`)?
8. Is there an authoritative Release 1 route list? Its absence is the largest single gap in this audit (`A-15`).

**On the release**

9. Path A or Path B — see `05_SCOPE_AND_TIMELINE.md`.
10. If #1427 will not be fixed before launch, is the instant-revocation claim being withdrawn from the product description in the meantime?

## Engagement terms, for the record

Fixed price $700, approximately 10 hours at $70/hr. Scope: a written review of the front-end codebase covering the R1 routes and screens identified as sufficiently built, delivering a readiness recommendation, prioritised findings with evidence and file/line references, security / architecture / performance / maintainability risks, remediation with indicative effort, and stated assumptions and exclusions. Delivery within three working days of access. This pack is that deliverable.

This completes the engagement as scoped. The pack is self-contained: findings, evidence, effort estimates and exit criteria stand on what was observed, and none of them depend on further answers.

Post-audit development is outside this engagement. If the blockers are to be contracted separately, the cleanest structure is a fixed price covering steps 0 to 4 of `03_REMEDIATION_PLAN.md`.
