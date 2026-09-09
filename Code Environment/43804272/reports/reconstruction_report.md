# 43804272 reconstruction report

## Outcome

The package contains one completed zero-domain baseline and 5 independently runnable repositories representing the exact state immediately before every selected target message. Every requirement event was replayed atomically by source message, and every target boundary matched both the pre-task and post-task Gold state.

Two of the five selected targets are marked for RQ4 by the Gold data (T001 and T003). The remaining snapshots are retained so that the temporal replay is complete and auditable. T005 is an ambiguity event and is explicitly marked as requiring clarification rather than a code mutation.

## Fidelity boundary

The local corpus describes an Android/iOS product and its behavior, but it does not contain a frozen historical native source archive. The package therefore uses a deterministic, dependency-free Node.js behavior harness. It is an executable state reconstruction, not a claim that the original Objective-C/Android files were recovered.

The Requirement State Graph contains 23 requirements and 60 events. `REQ_ANDROID_APP_BUNDLE` has no graph events or state node; it is recorded as a graph gap and is not silently fabricated in any snapshot.

## Verification

- Clean install: `npm ci --ignore-scripts`
- Syntax, build, and endpoint tests: `npm run check`
- C_env project-specific future-state leakage scan: PASS
- C_env and target credential/PII scans: PASS
- Gold pre-state and post-state comparisons: 5/5 PASS
- ZIP CRC, safe-path, no-symlink, and no-`.git` checks: PASS

See `validation_report.json`, `replay_manifest.json`, `independent_audit_report.json` (created by the independent audit), and each target's `manifest.json` for machine-readable evidence.
