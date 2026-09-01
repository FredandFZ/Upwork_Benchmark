# 42204309 Complete Code-State Reconstruction

## Outcome

This package contains one completed composite `C_env` and 25 independently
consumable repositories representing `C(t⁻)` for every selected target in
`gold_states.json`. The state sequence was produced by replaying every event
group in message order and checking the selected pre/post boundaries against
the gold state maps.

## Evidence classification

- Smart-contract environment: reduced from an observed Solidity/Foundry
  milestone snapshot (high confidence for toolchain, not a final full product).
- Web/API environment: executable simulation based on chat evidence and the
  requirement state graph because no frontend/backend source was delivered.
- External platform work: represented as `non_code_action`; no fake repository
  implementation is introduced.
- Secrets and production identifiers: excluded or replaced by local placeholders.

## Replay audit

- Event count: 343
- Event-group count: 157
- Selected pre-boundaries matched: 25/25
- Selected post-boundaries matched: 25/25
- Same-message events were applied atomically after exporting the pre-state.

## Target inventory

| Target | Before message | Tracked states | Executable code features | Seeded historical defect | Repo SHA-256 |
| --- | ---: | ---: | ---: | --- | --- |
| T001 | 114 | 21 | 18 | — | `1e77bfec4784` |
| T002 | 156 | 30 | 27 | — | `669567481d0c` |
| T003 | 158 | 33 | 30 | — | `11e16b816c00` |
| T004 | 159 | 33 | 30 | — | `f62bcaefbc82` |
| T005 | 184 | 34 | 31 | — | `fb2c904b6345` |
| T006 | 195 | 40 | 35 | — | `e78a7d38be2e` |
| T007 | 210 | 40 | 34 | — | `2b6835d83d41` |
| T008 | 212 | 40 | 34 | layout_overlap_seed | `291ae68ea3a8` |
| T009 | 240 | 42 | 36 | — | `ba71512be956` |
| T010 | 288 | 42 | 36 | unconfirmed_rows_counted_seed | `b2fc5061dfe1` |
| T011 | 305 | 46 | 40 | — | `1e5c7ee33188` |
| T012 | 583 | 56 | 49 | — | `9fb1234afbd1` |
| T013 | 595 | 57 | 50 | — | `414b71dc012b` |
| T014 | 626 | 58 | 51 | — | `301bd82800d2` |
| T015 | 631 | 58 | 51 | — | `301bd82800d2` |
| T016 | 636 | 58 | 51 | — | `48f949f3bcf4` |
| T017 | 672 | 58 | 51 | — | `1608babf8038` |
| T018 | 674 | 58 | 51 | — | `dbd1dc28c99d` |
| T019 | 684 | 58 | 51 | — | `5cc1c4930d1e` |
| T020 | 688 | 58 | 51 | stale_metadata_seed | `a8199ea19ad7` |
| T021 | 701 | 58 | 51 | — | `9ed3d4de3e07` |
| T022 | 742 | 58 | 51 | — | `8091a9499a37` |
| T023 | 764 | 58 | 51 | — | `1bd1ef324822` |
| T024 | 781 | 59 | 52 | — | `886c6a68d4a8` |
| T025 | 785 | 59 | 52 | — | `886c6a68d4a8` |

`T008`, `T010`, and `T020` contain narrowly scoped historical defect shapes so
the target request can operate on a meaningful failing predecessor. Public
smoke tests verify only environment integrity and do not reveal the required fix.

## Validation

Overall validation: **PASS**.

Every repository passed its Node build, HTTP smoke test, Foundry compile, and
Foundry test using the common locked toolchain. The composite `C_env` also
passed a negative domain-term scan. All generated repositories passed the
secret-pattern scan.

## Important limitation

These are benchmark construction artifacts, not claimed historical Git commits.
They are temporally consistent, executable reconstructions. Exact production UI,
database schema, and backend framework cannot be recovered from the supplied
evidence because those source files are absent.
