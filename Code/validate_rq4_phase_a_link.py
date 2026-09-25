#!/usr/bin/env python3
"""Validate the 40-target RQ4 registry and its 80 Phase A packages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from rq_agent_input import RQMaterializationError, load_rq4_agent_judge_registry
from rq_run_identity import validate_package_manifest


ROOT = Path(__file__).resolve().parents[1]


class RQ4PhaseLinkError(ValueError):
    pass


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RQ4PhaseLinkError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RQ4PhaseLinkError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_phase_a_link(
    *, registry_path: Path, package_root: Path, repository_root: Path = ROOT
) -> dict[str, Any]:
    registry, indexed = load_rq4_agent_judge_registry(registry_path)
    manifests = sorted(package_root.rglob("package_manifest.json"))
    expected_keys = {
        (project_id, target_id, condition)
        for project_id, target_id in indexed
        for condition in ("C1", "C2")
        if indexed[(project_id, target_id)]["condition_eligibility"][condition]["rq4_eligible"]
    }
    seen: set[tuple[str, str, str]] = set()
    for path in manifests:
        package = validate_package_manifest(_json(path))
        key = (package.get("project_id"), package.get("target_id"), package.get("condition"))
        if key not in expected_keys or key in seen:
            raise RQ4PhaseLinkError(f"unexpected or duplicate Phase A package {key}")
        seen.add(key)
        record = indexed[(key[0], key[1])]
        rq4 = package.get("rq4")
        repository = package.get("repository")
        if not isinstance(rq4, Mapping) or not isinstance(repository, Mapping):
            raise RQ4PhaseLinkError(f"package {key} lacks private RQ4 bindings")
        if rq4.get("eligible") is not True or rq4.get("execution_ready") is not True:
            raise RQ4PhaseLinkError(f"package {key} is not Phase B ready")
        if rq4.get("registry_sha256") != registry["registry_sha256"]:
            raise RQ4PhaseLinkError(f"package {key} registry hash mismatch")
        if rq4.get("judge_contract") != registry.get("judge_contract"):
            raise RQ4PhaseLinkError(f"package {key} Judge contract mismatch")
        if rq4.get("acceptance_criteria") != record.get("acceptance_criteria"):
            raise RQ4PhaseLinkError(f"package {key} criteria mismatch")
        archive = repository_root / str(repository.get("archive_path", ""))
        manifest = repository_root / str(repository.get("manifest_path", ""))
        if not archive.is_file() or _sha256(archive) != repository.get("archive_sha256"):
            raise RQ4PhaseLinkError(f"package {key} repository archive is stale")
        if not manifest.is_file() or _sha256(manifest) != repository.get("manifest_sha256"):
            raise RQ4PhaseLinkError(f"package {key} repository manifest is stale")
        public_dir = path.parent.parent / "public"
        for name, expected_hash in package["public_files"].items():
            public_path = public_dir / name
            if not public_path.is_file() or _sha256(public_path) != expected_hash:
                raise RQ4PhaseLinkError(f"package {key} public input is stale: {name}")
        public_text = "\n".join(
            (public_dir / name).read_text(encoding="utf-8-sig")
            for name in package["public_files"]
        )
        for token in ("acceptance_criteria", "judge_contract", "rq4_agent_judge", "pre_repo.zip"):
            if token in public_text:
                raise RQ4PhaseLinkError(f"package {key} leaks private token {token!r}")
    if seen != expected_keys:
        raise RQ4PhaseLinkError(f"missing Phase A packages: {sorted(expected_keys - seen)[:10]}")
    return {
        "schema_version": "rq4-phase-a-link-validation-v1",
        "overall": "PASS",
        "target_count": len(indexed),
        "package_count": len(seen),
        "condition_counts": {
            condition: sum(key[2] == condition for key in seen)
            for condition in ("C1", "C2")
        },
        "phase_b_gate_policy": "OPEN_ONLY_AFTER_FROZEN_PHASE_A_ACT",
        "judge_policy": "PRIVATE_UNIVERSAL_AGENT_JUDGE_AFTER_FROZEN_PHASE_B",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "ccfa-workfiles" / "experiments" / "rq4-validation" / "rq4_agent_judge_registry.json")
    parser.add_argument("--package-root", type=Path, default=ROOT / "outputs_new" / "rq4_agent_inputs")
    args = parser.parse_args()
    try:
        result = validate_phase_a_link(
            registry_path=args.registry.resolve(),
            package_root=args.package_root.resolve(),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, RQ4PhaseLinkError, RQMaterializationError, ValueError) as exc:
        print(f"RQ4 Phase A link validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
