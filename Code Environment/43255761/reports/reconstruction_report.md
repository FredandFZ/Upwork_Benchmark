# 43255761 reconstruction report

## Outcome

The package contains one completed zero-domain Word environment and 6 independently runnable pre-event repositories. Atomic replay matches every Gold pre-state and post-state. The RQ4 targets are 43255761_T002, 43255761_T003, 43255761_T006.

Each repository generates a real, macro-free OOXML DOCX and exposes behavior-level title, list, and field operations. It uses no third-party package, network service, credential, or Microsoft Office dependency for build and test.

## Fidelity boundary

Five final DOCX deliverables are available, but their filenames and dataset placement do not prove availability at any selected earlier boundary. They are checksummed as external evidence and are never copied into a pre_repo. The generated documents are explicitly synthetic executable state projections, not claimed historical files.

The graph contains 35 requirements and 111 events. T005 correctly records new desired constraints and failures rather than pretending those failures were fixed. T003 preserves its independent open typography ambiguity. T006 retains the field-alignment failure and ambiguity in the pre-state.

The exact appearance requested from a customer-provided bullet reference cannot be recovered from the local corpus. The harness preserves that as an evidence gap instead of fabricating dimensions or colors.

## Verification

- Clean install, syntax, deterministic build, tests: PASS
- Macro-free DOCX ZIP/CRC/member/external-relationship checks: PASS
- Gold pre-state and post-state comparisons: 6/6 PASS
- Strict before-message future-event exclusion: PASS
- C_env zero-domain leakage and secret/PII scans: PASS
- ZIP safe path, CRC, no symlink, no .git: PASS
- Rendered-page visual QA: recorded in visual_qa_report.json after external review
