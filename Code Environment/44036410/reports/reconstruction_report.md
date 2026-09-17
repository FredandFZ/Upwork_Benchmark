# 44036410 reconstruction report

## Outcome

The package contains one completed zero-domain report environment and 3 independently runnable pre-event repositories. Atomic replay matches every Gold pre-state and post-state. The RQ4 targets are 44036410_T002, 44036410_T003.

Each repository builds a macro-free OOXML DOCX and a deterministic four-page PDF, and exposes behavior-level dashboard, explanation, vehicle-presentation, warning, footer, and report-code operations. It uses only the Node.js standard library and needs no network service, credential, or Office installation to build and test.

## Fidelity boundary

Four final DOCX deliverables and four matching PDF exports are present, but their dataset placement does not establish availability at any selected earlier boundary. They are checksummed only and never copied into C_env or a pre_repo. Generated files are explicitly synthetic executable state projections, not claimed historical files.

The graph contains 19 requirements and 73 events. T002 preserves the pre-request state before the dashboard/explanation/vehicle/warning/code change group. T003 preserves the observed dashboard-density, checkbox, warning-prominence, and report-code failures while retaining the already verified all-page footer behavior.

## Verification

- Clean install, syntax, deterministic build, tests: PASS
- Macro-free DOCX ZIP/CRC/member/external-relationship checks: PASS
- Four-page PDF structure and active-content checks: PASS
- Gold pre-state and post-state comparisons: 3/3 PASS
- Strict before-message future-event exclusion: PASS
- C_env zero-domain leakage and secret/PII scans: PASS
- ZIP safe path, CRC, no symlink, no .git: PASS
- PDF rendered-page visual QA: 4 PDFs / 16 pages inspected, PASS
- DOCX rendered-page visual QA: unavailable; structural OOXML validation is recorded
