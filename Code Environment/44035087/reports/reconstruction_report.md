# 44035087 reconstruction report

## Outcome

The package contains one completed zero-domain baseline and 4 independently runnable repositories representing the exact state immediately before every selected target message. Every requirement event was replayed atomically by source message, and every target boundary matched both the pre-task and post-task Gold state.

3 of the 4 selected targets are marked for RQ4 by the Gold data (44035087_T001, 44035087_T003, 44035087_T004). Every selected snapshot is retained so that the temporal replay remains complete and auditable.

## Fidelity boundary

The local corpus describes a WordPress/Elementor website and its responsive behavior, but it does not contain a frozen historical theme, plugin set, database, uploads archive, or hosting snapshot. The package therefore uses a deterministic, dependency-free Node.js behavior harness. It is an executable state reconstruction, not a claim that the original CMS files were recovered.

The Requirement State Graph contains 22 requirements and 62 events. Only graph-backed states are projected; hosting credentials, the live domain, and raw chat content are never copied into a repository.

## Verification

- Clean install: `npm ci --ignore-scripts`
- Syntax, build, and endpoint tests: `npm run check`
- C_env project-specific future-state leakage scan: PASS
- C_env and target credential/PII scans: PASS
- Gold pre-state and post-state comparisons: 4/4 PASS
- ZIP CRC, safe-path, no-symlink, and no-`.git` checks: PASS

See `validation_report.json`, `replay_manifest.json`, `independent_audit_report.json` (created by the independent audit), and each target's `manifest.json` for machine-readable evidence.
