# 43255761

Deterministic OOXML Word-template generator exposing current styles, fields, layout, localization, and interaction behavior.

## Commands

- `python scripts/build.py`
- `python scripts/check.py`
- `python -m unittest discover -s tests`
- `python src/cli.py list`
- `python scripts/serve.py`

## Structured artifact contract

Edit `src/artifact_model.py`, build the repository, then inspect the generated structure with `python scripts/inspect_artifacts.py`.
