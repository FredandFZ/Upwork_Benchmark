# 43214420

Deterministic KiCad-compatible schematic and PCB generator with structural checks for the currently active hardware design state.

## Commands

- `python scripts/build.py`
- `python scripts/check.py`
- `python -m unittest discover -s tests`
- `python src/cli.py list`
- `python scripts/serve.py`

## Structured artifact contract

Edit `src/artifact_model.py`, build the repository, then inspect the generated structure with `python scripts/inspect_artifacts.py`.
