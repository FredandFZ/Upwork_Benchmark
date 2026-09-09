# 43772711 reconstruction report

## Outcome

The package contains one completed zero-domain baseline and 5 independently runnable repositories representing the exact state immediately before every selected target message. Every requirement event was replayed atomically by source message, and every target boundary matched both the pre-task and post-task Gold state.

2 of the 5 selected targets are marked for RQ4 by the Gold data (43772711_T003, 43772711_T005). Every selected snapshot is retained so that the temporal replay remains complete and auditable.

## Fidelity boundary

The local corpus contains four landing-page design PNGs and describes a plain HTML/Tailwind website, static AWS deployment, and a separate React/TypeScript console. It does not contain the frozen historical HTML/CSS, Tailwind inputs, Figma export, or console repository. The package therefore uses a deterministic, dependency-free Node.js behavior harness. It is an executable state reconstruction, not a claim that the original source files were recovered.

The Requirement State Graph contains 24 requirements and 68 events. Only graph-backed states are projected; personal contact details, raw deployment URLs, and raw chat content are never copied into a repository. The PNG deliverables are checksummed as evidence but not embedded because they are not source code and their exact temporal provenance is not established by Gold.

## Verification

- Clean install: `npm ci --ignore-scripts`
- Syntax, build, and endpoint tests: `npm run check`
- C_env project-specific future-state leakage scan: PASS
- C_env and target credential/PII scans: PASS
- Gold pre-state and post-state comparisons: 5/5 PASS
- ZIP CRC, safe-path, no-symlink, and no-`.git` checks: PASS

See `validation_report.json`, `replay_manifest.json`, `independent_audit_report.json` (created by the independent audit), and each target's `manifest.json` for machine-readable evidence.
