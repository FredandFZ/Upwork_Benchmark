# 43214420 reconstruction report

## Outcome

The package contains one completed zero-domain PCB environment and 27 independently runnable pre-event repositories. Atomic replay matches every Gold pre-state and post-state. The RQ4 targets are 43214420_T001, 43214420_T002, 43214420_T016, 43214420_T017, 43214420_T026.

Each repository builds deterministic KiCad-compatible board/schematic fixtures and an exact JSON design-state artifact. Behavior operations expose mechanical envelope, connector layout, pin breakout, power safety, input interfaces, and manufacturing status. The harness uses only the Node.js standard library and needs no network service, credential, or KiCad installation for build and tests.

## Fidelity boundary

The final deliverable tree contains 78 files, including primary KiCad sources, production exports, libraries, 3D models, and a BOM. Its dataset placement does not establish availability at earlier boundaries, so it is checksummed only and never copied into C_env or a pre_repo. Generated fixtures are synthetic executable state projections, not claimed historical boards.

The graph contains 57 requirements and 236 events across 27 target boundaries. RQ4 covers battery protection/connector introduction (T001), mechanical and battery-access refinement (T002), separate-board connector placement (T016), the unresolved full-pin-breakout question plus BOM failure transition (T017), and the multi-requirement input/power-access change group (T026).

## Verification

- Clean install, syntax, deterministic build, tests: PASS
- KiCad root, balanced s-expression, and Edge.Cuts checks: PASS
- Exact design-state artifact comparison: PASS
- Gold pre-state and post-state comparisons: 27/27 PASS
- Strict before-message future-event exclusion: PASS
- C_env zero-domain leakage and secret/PII scans: PASS
- ZIP safe path, CRC, no symlink, no .git: PASS
- Native kicad-cli ERC/DRC: not run because kicad-cli is unavailable
