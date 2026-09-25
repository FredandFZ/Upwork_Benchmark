#!/usr/bin/env python3
"""Mechanically audit RQ4 agent-visible repositories for evaluator leakage.

The audit is deliberately independent from the Code Environment builder.  It
can inspect a directory or archive, recursively opens ZIP/DOCX containers, and
performs a conservative stdlib-only text extraction from PDFs.  Findings are
never self-resolving: a clean rerun is required before the eligibility gate can
pass.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, Iterable, Mapping, Sequence
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE_DEPTH = 5
MAX_ARCHIVE_MEMBERS = 20_000
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


class LeakageAuditError(RuntimeError):
    """The audit inputs are missing, malformed, or unsafe to inspect."""


_TEXT_RULES = {
    "INTERNAL_REQUIREMENT_ID": re.compile(r"\bREQ_[A-Z][A-Z0-9_]*\b"),
    "INTERNAL_STATE_OR_EVENT_ID": re.compile(
        r"\b[A-Z][A-Z0-9_]+_[SE][0-9]{3,}\b"
    ),
    "INTERNAL_TARGET_ID": re.compile(r"\b[0-9]{6,}_T[0-9]{3,}\b"),
    "ACCEPTANCE_CRITERIA_LEAK": re.compile(
        r"\bacceptance[ _-]?criteria\b", re.IGNORECASE
    ),
    "HIDDEN_VALIDATOR_LEAK": re.compile(
        r"\bhidden[ _-]?(?:validator|tests?)\b|\brq4[ _-]?validator\b",
        re.IGNORECASE,
    ),
    "REFERENCE_DELIVERY_LEAK": re.compile(
        r"\breference[ _-]?(?:delivery|implementation|patch|solution)\b",
        re.IGNORECASE,
    ),
    "PRIVATE_GOLD_LEAK": re.compile(
        r"\b(?:gold[ _-]?(?:state|transition|answer)|work[ _-]?item|calibration[ _-]?result)\b",
        re.IGNORECASE,
    ),
}

_PATH_RULES = {
    "PRIVATE_EVALUATOR_PATH": re.compile(
        r"(?:^|/)(?:acceptance[_ -]?criteria|hidden[_ -]?(?:validator|tests?)|"
        r"validators?|reference[_ -]?(?:delivery|implementation|patch|solution)|"
        r"gold[_ -]?(?:state|transition|answer)|work[_ -]?item|calibration)(?:[./_-]|$)",
        re.IGNORECASE,
    ),
    "INTERNAL_ID_IN_PATH": re.compile(
        r"(?:REQ_[A-Z0-9_]+|[0-9]{6,}_T[0-9]{3,})"
    ),
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LeakageAuditError(f"cannot read {path}: {exc}") from exc


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _flatten_leaves(value: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        if not value:
            yield prefix, value
        for key in sorted(value, key=str):
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten_leaves(value[key], child)
    elif isinstance(value, list):
        if not value:
            yield prefix, value
        for index, item in enumerate(value):
            yield from _flatten_leaves(item, f"{prefix}[{index}]")
    else:
        yield prefix, value


_MISSING = object()


def _changed_post_leaves(
    before: Any, after: Any, prefix: str = ""
) -> Iterable[tuple[str, Any]]:
    if isinstance(after, Mapping):
        prior = before if isinstance(before, Mapping) else {}
        for key in sorted(after, key=str):
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from _changed_post_leaves(prior.get(key, _MISSING), after[key], child)
        return
    if isinstance(after, list):
        if before != after:
            yield from _flatten_leaves(after, prefix)
        return
    if before is _MISSING or before != after:
        yield prefix, after


def _current_state_source(agent_visible: Path) -> str:
    try:
        if agent_visible.is_dir():
            return (agent_visible / "src" / "current_state.py").read_text(encoding="utf-8")
        with zipfile.ZipFile(agent_visible) as archive:
            return archive.read("src/current_state.py").decode("utf-8")
    except (OSError, KeyError, UnicodeDecodeError, zipfile.BadZipFile):
        return ""


def _current_state_features(agent_visible: Path) -> list[Any]:
    source = _current_state_source(agent_visible)
    if not source:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    features: Any = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "FEATURES" for target in node.targets):
            try:
                features = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                return []
            break
    if not isinstance(features, list):
        return []
    return features


def _current_state_pre_values(agent_visible: Path) -> set[str]:
    """Read the builder's public FEATURES literal as the complete legitimate pre-state."""

    features = _current_state_features(agent_visible)
    if not features:
        return set()
    return {
        _canonical(value)
        for _, value in _flatten_leaves(features)
        if value is not None
    }


def _future_value_records(
    work_item: Mapping[str, Any], *, additional_pre_values: set[str] | None = None,
    legitimate_pre_text: str = "", legitimate_pre_strings: set[str] | None = None,
) -> list[dict[str, Any]]:
    pre_features = work_item.get("pre_task_observable_features", {})
    post_features = work_item.get("post_task_observable_features", {})
    if not isinstance(pre_features, Mapping) or not isinstance(post_features, Mapping):
        raise LeakageAuditError("work item observable feature maps are missing")

    pre_values = {
        _canonical(value)
        for _, value in _flatten_leaves(pre_features)
        if value is not None
    }
    pre_values.update(additional_pre_values or set())
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for requirement_id in sorted(post_features, key=str):
        before = pre_features.get(requirement_id, _MISSING)
        after = post_features[requirement_id]
        for path, value in _changed_post_leaves(before, after):
            if value is None:
                continue
            if path.split(".", 1)[0].split("[", 1)[0] in {
                "components",
                "contexts",
                "execution",
                "lifecycle",
            }:
                continue
            encoded = _canonical(value)
            # A value already visible anywhere in the pre-state is not a
            # future-only answer token, even if it moved to another field.
            if encoded in pre_values:
                continue
            if isinstance(value, str) and value:
                # A later field can reuse a token already visible inside an
                # earlier compound value.  That is not a hidden answer leak.
                token = re.compile(rf"(?<!\w){re.escape(value)}(?!\w)")
                if (len(value) >= 4 and value in legitimate_pre_text) or token.search(
                    legitimate_pre_text
                ):
                    continue
                if len(value) >= 4 and any(
                    value in prior for prior in (legitimate_pre_strings or set())
                ):
                    continue
            key = (path, encoded)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "requirement_id": str(requirement_id),
                    "path": path,
                    "leaf_key": re.sub(r"\[[0-9]+\]$", "", path).rsplit(".", 1)[-1],
                    "value": value,
                    "canonical": encoded,
                    "value_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                }
            )
    return records


def _decode_texts(data: bytes) -> list[str]:
    texts: list[str] = []
    for encoding in ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "latin-1"):
        try:
            value = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if value not in texts:
            texts.append(value)
    return texts


def _pdf_unescape(value: bytes) -> bytes:
    def octal(match: re.Match[bytes]) -> bytes:
        return bytes([int(match.group(1), 8)])

    value = re.sub(rb"\\([0-7]{1,3})", octal, value)
    replacements = {
        rb"\\n": b"\n",
        rb"\\r": b"\r",
        rb"\\t": b"\t",
        rb"\\b": b"\b",
        rb"\\f": b"\f",
        rb"\\(": b"(",
        rb"\\)": b")",
        rb"\\\\": b"\\",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


def _pdf_text_payloads(data: bytes) -> list[bytes]:
    """Return raw, literal-string, hex-string, and Flate stream payloads."""

    payloads = [data]
    for match in re.finditer(rb"\((?:\\.|[^\\)])*\)", data, re.DOTALL):
        payloads.append(_pdf_unescape(match.group(0)[1:-1]))
    for match in re.finditer(rb"<([0-9A-Fa-f\s]{4,})>", data):
        compact = re.sub(rb"\s+", b"", match.group(1))
        if len(compact) % 2:
            compact += b"0"
        try:
            payloads.append(bytes.fromhex(compact.decode("ascii")))
        except ValueError:
            pass
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL):
        stream = match.group(1)
        header = data[max(0, match.start() - 1024) : match.start()]
        if b"/FlateDecode" in header:
            try:
                stream = zlib.decompress(stream)
            except zlib.error:
                continue
        payloads.append(stream)
        for literal in re.finditer(rb"\((?:\\.|[^\\)])*\)", stream, re.DOTALL):
            payloads.append(_pdf_unescape(literal.group(0)[1:-1]))
    return payloads


class _Audit:
    def __init__(self, future_values: Sequence[Mapping[str, Any]]) -> None:
        self.future_values = list(future_values)
        self.findings: list[dict[str, Any]] = []
        self._finding_keys: set[str] = set()
        self.scanned_artifacts = 0
        self.scanned_text_views = 0
        self.agent_blob_hashes: dict[str, set[str]] = {}

    def add(
        self,
        *,
        category: str,
        rule: str,
        artifact: str,
        evidence: str,
        match_sha256: str | None = None,
    ) -> None:
        record = {
            "category": category,
            "rule": rule,
            "artifact": artifact,
            "evidence": evidence,
            "match_sha256": match_sha256,
            "status": "UNRESOLVED",
            "severity": "BLOCKING",
            "required_action": "Remove the leaked material from every agent-visible surface and rerun the audit.",
        }
        fingerprint = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
        if fingerprint in self._finding_keys:
            return
        self._finding_keys.add(fingerprint)
        record["finding_fingerprint"] = fingerprint
        self.findings.append(record)

    def scan_path(self, artifact: str) -> None:
        normalized = artifact.replace("\\", "/")
        for rule, pattern in _PATH_RULES.items():
            match = pattern.search(normalized)
            if match:
                self.add(
                    category="AUTHORING_PACKAGE_BOUNDARY"
                    if rule == "PRIVATE_EVALUATOR_PATH"
                    else "GOLD_METADATA_LEAK",
                    rule=rule,
                    artifact=artifact,
                    evidence=f"forbidden path token at offset {match.start()}",
                    match_sha256=hashlib.sha256(match.group(0).encode("utf-8")).hexdigest(),
                )

    def scan_text(self, artifact: str, text: str) -> None:
        self.scanned_text_views += 1
        for rule, pattern in _TEXT_RULES.items():
            match = pattern.search(text)
            if match:
                category = {
                    "INTERNAL_REQUIREMENT_ID": "GOLD_METADATA_LEAK",
                    "INTERNAL_STATE_OR_EVENT_ID": "GOLD_METADATA_LEAK",
                    "INTERNAL_TARGET_ID": "GOLD_METADATA_LEAK",
                    "ACCEPTANCE_CRITERIA_LEAK": "VALIDATOR_LEAK",
                    "HIDDEN_VALIDATOR_LEAK": "VALIDATOR_LEAK",
                    "REFERENCE_DELIVERY_LEAK": "REFERENCE_LEAK",
                    "PRIVATE_GOLD_LEAK": "GOLD_METADATA_LEAK",
                }[rule]
                self.add(
                    category=category,
                    rule=rule,
                    artifact=artifact,
                    evidence=f"forbidden text token at character offset {match.start()}",
                    match_sha256=hashlib.sha256(match.group(0).encode("utf-8")).hexdigest(),
                )

        for record in self.future_values:
            value = record["value"]
            canonical = str(record["canonical"])
            found_at: int | None = None
            # Very short words (for example "left", "light", "header" or
            # asset tickers) collide heavily with ordinary source code.  They
            # require semantic review or a field-context rule rather than an
            # unconstrained substring match.
            if isinstance(value, str) and len(value.strip()) >= 7:
                found_at = text.find(value)
            elif isinstance(value, (int, float, bool)):
                leaf = re.escape(str(record["leaf_key"]))
                literal = re.escape(canonical)
                contextual = re.compile(
                    rf"[\"']?{leaf}[\"']?\s*[:=]\s*{literal}(?![A-Za-z0-9_.-])",
                    re.IGNORECASE,
                )
                match = contextual.search(text)
                found_at = match.start() if match else None
            elif isinstance(value, (list, dict)) and len(canonical) >= 8:
                found_at = text.find(canonical)
            if found_at is not None and found_at >= 0:
                self.add(
                    category="FUTURE_STATE_LEAK",
                    rule="FUTURE_STATE_EXACT_VALUE",
                    artifact=artifact,
                    evidence=(
                        f"future-only value for {record['requirement_id']}."
                        f"{record['path']} at character offset {found_at}"
                    ),
                    match_sha256=str(record["value_sha256"]),
                )

    def scan_blob(self, data: bytes, artifact: str, depth: int = 0) -> None:
        self.scanned_artifacts += 1
        self.scan_path(artifact)
        digest = _sha256_bytes(data)
        self.agent_blob_hashes.setdefault(digest, set()).add(artifact)
        if depth > MAX_ARCHIVE_DEPTH:
            self.add(
                category="AUTHORING_PACKAGE_BOUNDARY",
                rule="ARCHIVE_NESTING_LIMIT",
                artifact=artifact,
                evidence=f"archive nesting exceeds {MAX_ARCHIVE_DEPTH}",
            )
            return

        stream = io.BytesIO(data)
        if zipfile.is_zipfile(stream):
            stream.seek(0)
            try:
                with zipfile.ZipFile(stream) as archive:
                    infos = archive.infolist()
                    if len(infos) > MAX_ARCHIVE_MEMBERS:
                        self.add(
                            category="AUTHORING_PACKAGE_BOUNDARY",
                            rule="ARCHIVE_MEMBER_LIMIT",
                            artifact=artifact,
                            evidence=f"archive has {len(infos)} members",
                        )
                        return
                    total = 0
                    for info in infos:
                        member = info.filename.replace("\\", "/")
                        pure = PurePosixPath(member)
                        virtual = f"{artifact}!{member}"
                        unsafe = (
                            pure.is_absolute()
                            or ".." in pure.parts
                            or re.match(r"^[A-Za-z]:", member) is not None
                        )
                        mode = info.external_attr >> 16
                        if unsafe or stat.S_ISLNK(mode):
                            self.add(
                                category="AUTHORING_PACKAGE_BOUNDARY",
                                rule="UNSAFE_ARCHIVE_MEMBER",
                                artifact=virtual,
                                evidence="archive member is absolute, traversing, or a symlink",
                            )
                            continue
                        if info.is_dir():
                            self.scan_path(virtual)
                            continue
                        total += info.file_size
                        if info.file_size > MAX_MEMBER_BYTES or total > MAX_ARCHIVE_BYTES:
                            self.add(
                                category="AUTHORING_PACKAGE_BOUNDARY",
                                rule="ARCHIVE_EXPANSION_LIMIT",
                                artifact=virtual,
                                evidence="archive expansion exceeds the configured safety limit",
                            )
                            continue
                        try:
                            child = archive.read(info)
                        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                            self.add(
                                category="AUTHORING_PACKAGE_BOUNDARY",
                                rule="UNREADABLE_ARCHIVE_MEMBER",
                                artifact=virtual,
                                evidence=type(exc).__name__,
                            )
                            continue
                        self.scan_blob(child, virtual, depth + 1)
            except zipfile.BadZipFile as exc:
                self.add(
                    category="AUTHORING_PACKAGE_BOUNDARY",
                    rule="MALFORMED_ARCHIVE",
                    artifact=artifact,
                    evidence=type(exc).__name__,
                )
            return

        suffix = PurePosixPath(artifact.split("!")[-1]).suffix.lower()
        payloads = _pdf_text_payloads(data) if suffix == ".pdf" or data.startswith(b"%PDF-") else [data]
        for payload in payloads:
            for text in _decode_texts(payload):
                self.scan_text(artifact, text)


def _scan_input(audit: _Audit, path: Path, label: str) -> None:
    if not path.exists():
        raise LeakageAuditError(f"agent-visible input is missing: {path}")
    if path.is_symlink():
        audit.add(
            category="AUTHORING_PACKAGE_BOUNDARY",
            rule="AGENT_VISIBLE_SYMLINK",
            artifact=label,
            evidence="top-level agent-visible input is a symlink",
        )
        return
    if path.is_file():
        audit.scan_blob(path.read_bytes(), label)
        return
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        relative = child.relative_to(path).as_posix()
        artifact = f"{label}/{relative}"
        if child.is_symlink():
            audit.add(
                category="AUTHORING_PACKAGE_BOUNDARY",
                rule="AGENT_VISIBLE_SYMLINK",
                artifact=artifact,
                evidence="agent-visible tree contains a symlink",
            )
        elif child.is_file():
            audit.scan_blob(child.read_bytes(), artifact)


def _private_blob_hashes(path: Path) -> dict[str, list[str]]:
    """Inventory private package leaves for exact-copy boundary checks."""

    hashes: dict[str, list[str]] = {}

    def add_blob(data: bytes, artifact: str, depth: int = 0) -> None:
        if len(data) >= 16:
            hashes.setdefault(_sha256_bytes(data), []).append(artifact)
        if depth >= MAX_ARCHIVE_DEPTH:
            return
        stream = io.BytesIO(data)
        if not zipfile.is_zipfile(stream):
            return
        stream.seek(0)
        try:
            with zipfile.ZipFile(stream) as archive:
                for info in archive.infolist()[:MAX_ARCHIVE_MEMBERS]:
                    if info.is_dir() or info.file_size > MAX_MEMBER_BYTES:
                        continue
                    try:
                        add_blob(
                            archive.read(info),
                            f"{artifact}!{info.filename}",
                            depth + 1,
                        )
                    except (OSError, RuntimeError, zipfile.BadZipFile):
                        continue
        except zipfile.BadZipFile:
            return

    if not path.exists():
        raise LeakageAuditError(f"private package is missing: {path}")
    if path.is_file():
        add_blob(path.read_bytes(), path.name)
    else:
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            add_blob(child.read_bytes(), f"{path.name}/{child.relative_to(path).as_posix()}")
    return hashes


def _surface_identity(path: Path) -> dict[str, Any]:
    if path.is_file():
        return {"path": str(path), "kind": "FILE", "sha256": _sha256_file(path)}
    digest = hashlib.sha256()
    files = sorted(
        (
            (child.relative_to(path).as_posix(), child)
            for child in path.rglob("*")
            if child.is_file()
        ),
        key=lambda item: item[0],
    )
    for relative, child in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(child.read_bytes())
        digest.update(b"\0")
    return {
        "path": str(path),
        "kind": "DIRECTORY",
        "tree_sha256": digest.hexdigest(),
    }


def audit_leakage(
    *,
    agent_visible: Path,
    work_item_path: Path,
    private_packages: Sequence[Path] = (),
) -> dict[str, Any]:
    work_item = _read_json(work_item_path)
    if not isinstance(work_item, Mapping):
        raise LeakageAuditError("work item must be a JSON object")
    current_state_source = _current_state_source(agent_visible)
    current_features = _current_state_features(agent_visible)
    current_strings = {
        value
        for _, value in _flatten_leaves(current_features)
        if isinstance(value, str)
    }
    future_values = _future_value_records(
        work_item,
        additional_pre_values=_current_state_pre_values(agent_visible),
        legitimate_pre_text=current_state_source,
        legitimate_pre_strings=current_strings,
    )
    audit = _Audit(future_values)
    _scan_input(audit, agent_visible, agent_visible.name or "agent-visible")

    identity = _surface_identity(agent_visible)
    repository = work_item.get("code_environment", {})
    if isinstance(repository, Mapping):
        if identity["kind"] == "FILE":
            expected = repository.get("archive_sha256")
            actual = identity.get("sha256")
            source_kind = "archive"
        else:
            expected = repository.get("repository_tree_sha256")
            actual = identity.get("tree_sha256")
            source_kind = "repository tree"
        if isinstance(expected, str) and expected and actual != expected:
            audit.add(
                category="AUTHORING_PACKAGE_BOUNDARY",
                rule="AGENT_SURFACE_SOURCE_MISMATCH",
                artifact=str(agent_visible),
                evidence=f"agent-visible {source_kind} hash differs from the frozen work item",
                match_sha256=str(actual),
            )

    private_records = []
    for package in private_packages:
        crosses_boundary = (
            _path_is_within(package, agent_visible)
            if agent_visible.is_dir()
            else package.resolve() == agent_visible.resolve()
        )
        if crosses_boundary:
            audit.add(
                category="AUTHORING_PACKAGE_BOUNDARY",
                rule="PRIVATE_PACKAGE_INSIDE_AGENT_SURFACE",
                artifact=str(package),
                evidence="private validator/package path is inside the agent-visible surface",
            )
        package_hashes = _private_blob_hashes(package)
        for digest in sorted(set(package_hashes) & set(audit.agent_blob_hashes)):
            audit.add(
                category="AUTHORING_PACKAGE_BOUNDARY",
                rule="PRIVATE_PACKAGE_EXACT_COPY",
                artifact=sorted(audit.agent_blob_hashes[digest])[0],
                evidence=(
                    "agent-visible file exactly matches private package material: "
                    + sorted(package_hashes[digest])[0]
                ),
                match_sha256=digest,
            )
        private_records.append(
            {
                "path": str(package),
                "leaf_blob_count": sum(len(values) for values in package_hashes.values()),
            }
        )

    findings = sorted(
        audit.findings,
        key=lambda row: (row["category"], row["artifact"], row["rule"], row["finding_fingerprint"]),
    )
    for index, finding in enumerate(findings, 1):
        finding["finding_id"] = f"LEAK{index:04d}"
    unresolved = [row for row in findings if row["status"] == "UNRESOLVED"]
    overall = "PASS" if not unresolved else "BLOCK"
    return {
        "schema_version": "rq4-leakage-audit-v1",
        "project_id": work_item.get("project_id"),
        "target_id": work_item.get("target_id"),
        "audit_scope": "AGENT_VISIBLE_REPOSITORY_AND_PRIVATE_PACKAGE_BOUNDARY",
        "agent_visible": identity,
        "work_item": {
            "path": str(work_item_path),
            "sha256": _sha256_file(work_item_path),
        },
        "private_packages": private_records,
        "future_state_exact_value_count": len(future_values),
        "scanned_artifact_count": audit.scanned_artifacts,
        "scanned_text_view_count": audit.scanned_text_views,
        "finding_count": len(findings),
        "unresolved_finding_count": len(unresolved),
        "findings": findings,
        "overall": overall,
        "rq4_eligibility_gate": "PASS" if overall == "PASS" else "BLOCKED_BY_LEAKAGE",
        "resolution_policy": "Every finding is unresolved until the agent-visible surface is corrected and a clean audit rerun produces no finding.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-visible", type=Path, required=True)
    parser.add_argument("--work-item", type=Path, required=True)
    parser.add_argument("--private-package", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = audit_leakage(
            agent_visible=args.agent_visible,
            work_item_path=args.work_item,
            private_packages=args.private_package,
        )
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8", newline="\n")
        print(rendered, end="")
        return 0 if report["overall"] == "PASS" else 2
    except (OSError, LeakageAuditError) as exc:
        print(f"RQ4 leakage audit failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
