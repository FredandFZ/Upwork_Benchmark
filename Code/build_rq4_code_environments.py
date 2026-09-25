#!/usr/bin/env python3
"""Build project-scoped RQ4 Code Environments from the frozen new release."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import pprint
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLANS_ROOT = (
    ROOT / "ccfa-workfiles" / "experiments" / "rq4-code-environment" / "projects"
)
DEFAULT_OUTPUT_ROOT = ROOT / "Code Environment"
BUILD_STATUS = "READY_FOR_CODE_ENV_RECONSTRUCTION"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


class BuildError(RuntimeError):
    """The frozen sources cannot produce a valid Code Environment."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"{path} must contain a JSON object")
    return value


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_source(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise BuildError(f"unsafe source path: {relative}")
    path = (ROOT / Path(*pure.parts)).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise BuildError(f"source escapes repository: {relative}") from exc
    return path


def _verify_sources(plan: Mapping[str, Any]) -> dict[str, Path]:
    sources = plan.get("project_sources")
    if not isinstance(sources, Mapping):
        raise BuildError("project_sources is missing")
    resolved: dict[str, Path] = {}
    for name, source in sources.items():
        if not isinstance(source, Mapping):
            raise BuildError(f"invalid source record: {name}")
        path = _resolve_source(str(source.get("path", "")))
        if not path.is_file() or _sha256(path) != source.get("file_sha256"):
            raise BuildError(f"stale or missing source: {name} ({path})")
        resolved[str(name)] = path
    return resolved


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    result = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return result or "feature"


def _state_map(rows: Any) -> dict[str, str]:
    if not isinstance(rows, list):
        raise BuildError("Gold requirement_states must be an array")
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise BuildError("Gold state reference must be an object")
        requirement_id = str(row.get("requirement_id", ""))
        state_id = str(row.get("state_id", ""))
        if not requirement_id or not state_id or requirement_id in result:
            raise BuildError("invalid or duplicate Gold state reference")
        result[requirement_id] = state_id
    return result


def _replay(
    plan: Mapping[str, Any], graph: Mapping[str, Any], normalized: Mapping[str, Any]
) -> tuple[
    dict[str, dict[str, str]],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    messages = normalized.get("messages")
    if not isinstance(messages, list) or not messages:
        raise BuildError("normalized_project.messages is missing")
    message_order: dict[int, int] = {}
    for index, message in enumerate(messages):
        message_id = int(message["message_id"])
        if message_id in message_order:
            raise BuildError(f"duplicate normalized message {message_id}")
        message_order[message_id] = index

    requirement_by_id: dict[str, dict[str, Any]] = {}
    state_by_id: dict[str, dict[str, Any]] = {}
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    graphs = graph.get("requirement_graphs")
    if not isinstance(graphs, list):
        raise BuildError("requirement_graphs is missing")
    for graph_index, requirement in enumerate(graphs):
        requirement_id = str(requirement["requirement_id"])
        if requirement_id in requirement_by_id:
            raise BuildError(f"duplicate requirement {requirement_id}")
        requirement_by_id[requirement_id] = dict(requirement)
        for node in requirement.get("nodes", []):
            state_id = str(node["state_id"])
            if state_id in state_by_id:
                raise BuildError(f"duplicate state {state_id}")
            state_by_id[state_id] = dict(node)
        for edge_index, edge in enumerate(requirement.get("edges", [])):
            message_id = int(edge["source_message_id"])
            if message_id not in message_order:
                raise BuildError(f"event source message is missing: {message_id}")
            grouped[message_id].append(
                {
                    **dict(edge),
                    "requirement_id": requirement_id,
                    "graph_index": graph_index,
                    "edge_index": edge_index,
                }
            )

    targets = plan.get("targets")
    if not isinstance(targets, list):
        raise BuildError("plan targets are missing")
    target_by_message: dict[int, dict[str, Any]] = {}
    for target in targets:
        message_id = int(target["target_message_id"])
        if message_id in target_by_message:
            raise BuildError(f"multiple selected targets at message {message_id}")
        target_by_message[message_id] = dict(target)

    current: dict[str, str] = {}
    snapshots: dict[str, dict[str, str]] = {}
    ledger: list[dict[str, Any]] = []
    for message_id in sorted(grouped, key=lambda value: message_order[value]):
        events = sorted(
            grouped[message_id],
            key=lambda row: (int(row["graph_index"]), int(row["edge_index"])),
        )
        target = target_by_message.get(message_id)
        if target is not None:
            expected_pre = _state_map(target["state_refs"]["pre_task"])
            if current != expected_pre:
                raise BuildError(f"{target['target_id']} pre-state differs from Gold")
            if target["plan_status"] == BUILD_STATUS:
                snapshots[str(target["target_id"])] = dict(current)

        applied: list[dict[str, Any]] = []
        for event in events:
            requirement_id = str(event["requirement_id"])
            before = event.get("from_state_id")
            if current.get(requirement_id) != before:
                raise BuildError(
                    f"{event['event_id']} replay chain mismatch for {requirement_id}"
                )
            after = str(event["to_state_id"])
            if after not in state_by_id:
                raise BuildError(f"{event['event_id']} points to unknown state {after}")
            current[requirement_id] = after
            applied.append(
                {
                    "event_id": event["event_id"],
                    "event_type": event["event_type"],
                    "requirement_id": requirement_id,
                    "from_state_id": before,
                    "to_state_id": after,
                }
            )

        if target is not None:
            expected_post = _state_map(target["state_refs"]["post_task"])
            if current != expected_post:
                raise BuildError(f"{target['target_id']} post-state differs from Gold")
        ledger.append(
            {
                "message_id": message_id,
                "message_position": message_order[message_id],
                "selected_target_id": target.get("target_id") if target else None,
                "event_count": len(applied),
                "events": applied,
            }
        )

    expected_build_ids = {
        str(target["target_id"])
        for target in targets
        if target["plan_status"] == BUILD_STATUS
    }
    if set(snapshots) != expected_build_ids:
        missing = sorted(expected_build_ids - set(snapshots))
        raise BuildError(f"build snapshots are missing: {missing}")
    return snapshots, ledger, requirement_by_id, state_by_id


def _features_for_state(
    state: Mapping[str, str],
    requirement_by_id: Mapping[str, Mapping[str, Any]],
    state_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    features: list[dict[str, Any]] = []
    mappings: list[dict[str, str]] = []
    used_slugs: set[str] = set()
    for requirement_id in sorted(state):
        node = state_by_id[state[requirement_id]]
        lifecycle = node.get("lifecycle_status") or "ACTIVE"
        if lifecycle in {"REMOVED", "DEFERRED"}:
            continue
        requirement = requirement_by_id[requirement_id]
        title = str(requirement.get("title") or "Current feature")
        base_slug = _slug(title)
        slug = base_slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        used_slugs.add(slug)
        scope = node.get("scope") if isinstance(node.get("scope"), Mapping) else {}
        execution = (
            node.get("execution") if isinstance(node.get("execution"), Mapping) else {}
        )
        public_execution = {
            key: execution[key]
            for key in ("status", "observed_behavior")
            if key in execution
        }
        feature = {
            "slug": slug,
            "title": title,
            "lifecycle": lifecycle,
            "attributes": node.get("attributes") or {},
            "components": list(scope.get("components") or []),
            "contexts": list(scope.get("contexts") or []),
            "execution": public_execution,
        }
        features.append(feature)
        mappings.append(
            {
                "requirement_id": requirement_id,
                "state_id": state[requirement_id],
                "code_path": "src/current_state.py",
                "behavior_key": slug,
            }
        )
    return features, mappings


RUNTIME_SOURCE = r'''from __future__ import annotations

import html
import json
from pathlib import Path
import zipfile
from xml.sax.saxutils import escape

from current_state import FEATURES, PROJECT


def feature_catalog():
    return [dict(item) for item in FEATURES]


def get_feature(slug):
    for feature in FEATURES:
        if feature["slug"] == slug:
            return dict(feature)
    raise KeyError(slug)


def simulate(slug):
    feature = get_feature(slug)
    execution = feature.get("execution") or {}
    return {
        "slug": slug,
        "status": execution.get("status", "AVAILABLE"),
        "observed_behavior": execution.get("observed_behavior"),
        "attributes": feature.get("attributes", {}),
    }


def _value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _feature_html(feature):
    rows = "".join(
        f"<dt>{html.escape(str(key))}</dt><dd>{html.escape(_value(value))}</dd>"
        for key, value in sorted(feature.get("attributes", {}).items())
    )
    execution = feature.get("execution") or {}
    status = html.escape(str(execution.get("status", "AVAILABLE")))
    return (
        f'<article class="feature" data-feature="{html.escape(feature["slug"])}" '
        f'data-status="{status}"><h2>{html.escape(feature["title"])}</h2>'
        f"<p class=\"status\">{status}</p><dl>{rows}</dl></article>"
    )


def _render_html(mobile=False):
    body = "".join(_feature_html(feature) for feature in FEATURES)
    viewport = '<meta name="viewport" content="width=device-width,initial-scale=1">'
    mode = "mobile" if mobile else "web"
    return f"""<!doctype html><html><head><meta charset="utf-8">{viewport}
<title>{html.escape(PROJECT["title"])}</title><style>
body{{font-family:system-ui;margin:auto;max-width:{'430px' if mobile else '1100px'};padding:2rem;background:#f4f7fb;color:#172033}}
.feature{{background:white;border:1px solid #d7deea;border-radius:12px;padding:1rem;margin:1rem 0}}
dt{{font-weight:700;margin-top:.6rem}}dd{{margin-left:0;color:#3f4b61}}.status{{font-size:.8rem;color:#52627a}}
</style></head><body data-mode="{mode}"><header><h1>{html.escape(PROJECT["title"])}</h1>
<p>{html.escape(PROJECT["description"])}</p></header><main>{body}</main></body></html>"""


def _zip_member(archive, name, content):
    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content.encode("utf-8"))


def _document_xml(title):
    paragraphs = [title]
    for feature in FEATURES:
        paragraphs.append(feature["title"])
        for key, value in sorted(feature.get("attributes", {}).items()):
            paragraphs.append(f"{key}: {_value(value)}")
        execution = feature.get("execution") or {}
        if execution.get("status"):
            paragraphs.append(f"Status: {execution['status']}")
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}<w:sectPr/></w:body></w:document>"""


def _build_docx(path, title):
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    with zipfile.ZipFile(path, "w") as archive:
        _zip_member(archive, "[Content_Types].xml", content_types)
        _zip_member(archive, "_rels/.rels", rels)
        _zip_member(archive, "word/document.xml", _document_xml(title))


def _build_pdf(path, title):
    lines = [title, *[item["title"] for item in FEATURES[:24]]]
    escaped = [line.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
    commands = ["BT", "/F1 11 Tf", "72 760 Td"]
    for index, line in enumerate(escaped):
        if index:
            commands.append("0 -24 Td")
        commands.append(f"({line}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects)+1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(data)


def _kicad_files(output):
    labels = "\n".join(f'  (text "{feature["title"].replace(chr(34), chr(39))}" (exclude_from_sim no) (at 20 {20 + index * 5} 0) (effects (font (size 1.27 1.27))))' for index, feature in enumerate(FEATURES[:30]))
    schematic = f"""(kicad_sch (version 20231120) (generator eeschema)
  (uuid 00000000-0000-0000-0000-000000000001)
  (paper "A4")
  (lib_symbols)
{labels}
  (sheet_instances (path "/" (page "1")))
)\n"""
    pcb = """(kicad_pcb (version 20240108) (generator pcbnew)
  (general (thickness 1.6))
  (paper "A4")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user "b.silkscreen") (37 "F.SilkS" user "f.silkscreen") (44 "Edge.Cuts" user))
  (setup (pad_to_mask_clearance 0))
  (gr_rect (start 0 0) (end 100 80) (stroke (width 0.05) (type default)) (fill none) (layer "Edge.Cuts"))
)\n"""
    (output / "design.kicad_sch").write_text(schematic, encoding="utf-8")
    (output / "design.kicad_pcb").write_text(pcb, encoding="utf-8")
    summary = "\n".join([PROJECT["title"], *[f"- {item['title']}" for item in FEATURES]]) + "\n"
    (output / "design-summary.txt").write_text(summary, encoding="utf-8")


def build(output="dist"):
    output = Path(output)
    if output.exists():
        import shutil
        shutil.rmtree(output)
    output.mkdir(parents=True)
    renderer = PROJECT["renderer"]
    if renderer == "web":
        (output / "index.html").write_text(_render_html(False), encoding="utf-8")
        (output / "catalog.json").write_text(json.dumps(feature_catalog(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif renderer == "mobile":
        (output / "mobile-preview.html").write_text(_render_html(True), encoding="utf-8")
        (output / "app-config.json").write_text(json.dumps(feature_catalog(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif renderer == "kicad":
        _kicad_files(output)
    elif renderer == "docx":
        _build_docx(output / "template.docx", PROJECT["title"])
        (output / "template-preview.html").write_text(_render_html(False), encoding="utf-8")
    elif renderer == "report":
        _build_docx(output / "security-report.docx", PROJECT["title"])
        _build_pdf(output / "security-report.pdf", PROJECT["title"])
        (output / "report-preview.html").write_text(_render_html(False), encoding="utf-8")
    else:
        raise ValueError(f"unknown renderer: {renderer}")
    return output


def check(output="dist"):
    output = Path(output)
    expected = [output / name.removeprefix("dist/") for name in PROJECT["primary_artifacts"]]
    missing = [str(path) for path in expected if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise RuntimeError(f"missing build artifacts: {missing}")
    renderer = PROJECT["renderer"]
    if renderer in {"docx", "report"}:
        name = "template.docx" if renderer == "docx" else "security-report.docx"
        with zipfile.ZipFile(output / name) as archive:
            assert archive.testzip() is None
            assert "word/document.xml" in archive.namelist()
    if renderer == "report":
        assert (output / "security-report.pdf").read_bytes().startswith(b"%PDF-")
    if renderer == "kicad":
        for name in ("design.kicad_sch", "design.kicad_pcb"):
            text = (output / name).read_text(encoding="utf-8")
            assert text.count("(") == text.count(")")
    return {"renderer": renderer, "artifact_count": len(expected), "feature_count": len(FEATURES)}
'''


CLI_SOURCE = r'''from __future__ import annotations

import argparse
import json

from runtime import build, check, feature_catalog, get_feature, simulate


def main():
    parser = argparse.ArgumentParser(description="Inspect and exercise the current project behavior.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("slug")
    run = sub.add_parser("simulate")
    run.add_argument("slug")
    sub.add_parser("build")
    sub.add_parser("check")
    args = parser.parse_args()
    if args.command in {None, "list"}:
        value = feature_catalog()
    elif args.command == "show":
        value = get_feature(args.slug)
    elif args.command == "simulate":
        value = simulate(args.slug)
    elif args.command == "build":
        value = {"output": str(build())}
    else:
        value = check()
    print(json.dumps(value, ensure_ascii=False, indent=2))
    if args.command == "simulate" and value.get("status") == "FAILED":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


BUILD_SOURCE = '''from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from runtime import build

build(ROOT / "dist")
print("build complete")
'''


CHECK_SOURCE = '''from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from runtime import check

print(json.dumps(check(ROOT / "dist"), indent=2))
'''


SERVE_SOURCE = '''from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from runtime import build, feature_catalog

build(ROOT / "dist")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/features":
            payload = json.dumps(feature_catalog(), ensure_ascii=False).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers(); self.wfile.write(payload); return
        candidates = [ROOT / "dist" / "index.html", ROOT / "dist" / "mobile-preview.html", ROOT / "dist" / "template-preview.html", ROOT / "dist" / "report-preview.html"]
        page = next((path for path in candidates if path.exists()), None)
        if self.path == "/" and page:
            payload = page.read_bytes(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(payload); return
        self.send_error(404)

ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
'''


TEST_SOURCE = r'''from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from current_state import FEATURES, PROJECT
from runtime import build, check, feature_catalog, get_feature, simulate


class RepositoryTest(unittest.TestCase):
    def test_catalog_has_unique_public_keys(self):
        slugs = [item["slug"] for item in feature_catalog()]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertFalse(any("REQ_" in json.dumps(item) for item in FEATURES))

    def test_each_feature_is_executable(self):
        for item in FEATURES:
            self.assertEqual(get_feature(item["slug"])["title"], item["title"])
            self.assertIn("status", simulate(item["slug"]))

    def test_clean_build_and_artifact_check(self):
        with tempfile.TemporaryDirectory() as directory:
            build(directory)
            result = check(directory)
            self.assertEqual(result["renderer"], PROJECT["renderer"])
            self.assertEqual(result["feature_count"], len(FEATURES))


if __name__ == "__main__":
    unittest.main()
'''


def _materialize_repository(
    destination: Path,
    *,
    project_id: str,
    project_title: str,
    profile: Mapping[str, Any],
    features: list[dict[str, Any]],
) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    project = {
        "project_id": project_id,
        "title": project_title,
        "description": profile["description"],
        "artifact_class": profile["artifact_class"],
        "renderer": profile["renderer"],
        "primary_artifacts": profile["primary_artifacts"],
    }
    current_state = (
        "# Generated current behavior. Edit this module to implement requested changes.\n"
        + "PROJECT = "
        + pprint.pformat(project, sort_dicts=True, width=100)
        + "\n\nFEATURES = "
        + pprint.pformat(features, sort_dicts=True, width=100)
        + "\n"
    )
    _write_text(destination / "src" / "current_state.py", current_state)
    _write_text(destination / "src" / "runtime.py", RUNTIME_SOURCE)
    _write_text(destination / "src" / "cli.py", CLI_SOURCE)
    _write_text(destination / "scripts" / "build.py", BUILD_SOURCE)
    _write_text(destination / "scripts" / "check.py", CHECK_SOURCE)
    _write_text(destination / "scripts" / "serve.py", SERVE_SOURCE)
    _write_text(destination / "tests" / "test_repository.py", TEST_SOURCE)
    _write_text(
        destination / "README.md",
        f"# {project_title}\n\n"
        f"{profile['description']}\n\n"
        "## Commands\n\n"
        "- `python scripts/build.py`\n"
        "- `python scripts/check.py`\n"
        "- `python -m unittest discover -s tests`\n"
        "- `python src/cli.py list`\n"
        "- `python scripts/serve.py`\n",
    )
    _write_text(
        destination / "Makefile",
        "build:\n\tpython scripts/build.py\n\n"
        "check:\n\tpython scripts/check.py\n\n"
        "test:\n\tpython -m unittest discover -s tests\n",
    )
    _write_text(
        destination / ".gitignore",
        "__pycache__/\n*.pyc\n.venv/\n",
    )


def _run(command: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    record = {
        "command": command,
        "exit_code": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }
    if result.returncode:
        raise BuildError(
            f"command failed in {cwd}: {command}\n{result.stdout}\n{result.stderr}"
        )
    return record


def _clean_runtime_files(root: Path) -> None:
    for directory in sorted(root.rglob("__pycache__"), reverse=True):
        shutil.rmtree(directory)
    for path in root.rglob("*.pyc"):
        path.unlink()


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        (
            (path.relative_to(root).as_posix(), path)
            for path in root.rglob("*")
            if path.is_file()
        ),
        key=lambda item: item[0],
    )
    for relative, path in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _zip_repository(source: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        files = sorted(
            (
                (path.relative_to(source).as_posix(), path)
                for path in source.rglob("*")
                if path.is_file()
            ),
            key=lambda item: item[0],
        )
        for relative, path in files:
            info = zipfile.ZipInfo(relative, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def _audit_archive(archive_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise BuildError(f"CRC failure in {archive_path}")
        names = archive.namelist()
        if not names:
            raise BuildError(f"empty archive: {archive_path}")
        for name in names:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts:
                raise BuildError(f"unsafe archive member: {name}")
            mode = archive.getinfo(name).external_attr >> 16
            if (mode & 0o170000) == 0o120000:
                raise BuildError(f"symlink in archive: {name}")
    return {"member_count": len(names), "crc": "PASS", "path_safety": "PASS"}


def _audit_repository(root: Path) -> dict[str, Any]:
    forbidden = {
        "internal_requirement_id": re.compile(r"\bREQ_[A-Z0-9_]+\b"),
        "internal_state_or_event_id": re.compile(r"\b[A-Z][A-Z0-9_]+_[SE]\d{3}\b"),
        "hidden_evaluator_material": re.compile(
            r"acceptance_criteria|hidden[_ -]?validator|reference[_ -]?delivery|build plan",
            re.IGNORECASE,
        ),
        "private_key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
        "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    }
    hits: list[dict[str, str]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.suffix.lower() in {".zip", ".docx", ".pdf", ".png", ".jpg"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in forbidden.items():
            match = pattern.search(text)
            if match:
                hits.append(
                    {
                        "file": path.relative_to(root).as_posix(),
                        "rule": name,
                        "match": match.group(0),
                    }
                )
    if hits:
        raise BuildError(f"agent-visible leakage detected: {hits[:5]}")
    return {"status": "PASS", "files_checked": sum(1 for p in root.rglob("*") if p.is_file()), "hits": []}


def _validate_repository(repo: Path) -> list[dict[str, Any]]:
    commands = [
        [sys.executable, "scripts/build.py"],
        [sys.executable, "scripts/check.py"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
    ]
    return [_run(command, repo) for command in commands]


def _fresh_extract_validation(archive: Path, expected_hash: str) -> list[dict[str, Any]]:
    temp_root = ROOT / "tmp" / "rq4-code-environment-validation"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_root) as directory:
        extracted = Path(directory) / "repo"
        extracted.mkdir()
        with zipfile.ZipFile(archive) as package:
            package.extractall(extracted)
        records = _validate_repository(extracted)
        _clean_runtime_files(extracted)
        if _tree_hash(extracted) != expected_hash:
            raise BuildError(f"fresh extraction is not deterministic: {archive}")
        return records


def _flatten_target_events(target: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    event_ids: list[str] = []
    event_types: list[str] = []
    for transition in target.get("affected_transition_digest", []):
        event_ids.extend(str(value) for value in transition.get("event_ids", []))
        event_types.extend(str(value) for value in transition.get("event_types", []))
    return event_ids, event_types


def _build_project(
    plan_path: Path, output_root: Path, *, replace_existing: bool = False
) -> dict[str, Any]:
    plan = _read_json(plan_path)
    project_id = str(plan["project_id"])
    if plan.get("construction_policy") != "FROM_SCRATCH_NEW_RELEASE_ONLY":
        raise BuildError(f"{project_id} does not require a clean rebuild")
    profile = plan.get("repository_profile")
    if not isinstance(profile, Mapping):
        raise BuildError(f"{project_id} repository profile is missing")
    sources = _verify_sources(plan)
    graph = _read_json(sources["requirement_state_graph"])
    normalized = _read_json(sources["normalized_project"])
    validation = _read_json(sources["gold_state_validation"])
    if validation.get("status") != "PASSED":
        raise BuildError(f"{project_id} Gold validation has not passed")

    snapshots, ledger, requirement_by_id, state_by_id = _replay(
        plan, graph, normalized
    )
    staging_root = output_root / ".staging"
    staging_project = staging_root / project_id
    canonical_project = output_root / project_id
    if canonical_project.exists() and not replace_existing:
        raise BuildError(f"refusing to overwrite existing project: {canonical_project}")
    if staging_project.exists():
        shutil.rmtree(staging_project)
    staging_project.mkdir(parents=True)

    build_targets = [
        target for target in plan["targets"] if target["plan_status"] == BUILD_STATUS
    ]
    target_index: list[dict[str, Any]] = []
    validation_records: list[dict[str, Any]] = []
    try:
        baseline_repo = staging_project / ".baseline-work"
        _materialize_repository(
            baseline_repo,
            project_id=project_id,
            project_title=str(plan.get("project_title") or project_id),
            profile=profile,
            features=[],
        )
        baseline_commands = _validate_repository(baseline_repo)
        _clean_runtime_files(baseline_repo)
        baseline_audit = _audit_repository(baseline_repo)
        baseline_archive = (
            staging_project / "C_env" / f"{project_id}_C_env_complete.zip"
        )
        _zip_repository(baseline_repo, baseline_archive)
        baseline_archive_audit = _audit_archive(baseline_archive)
        baseline_hash = _tree_hash(baseline_repo)
        baseline_fresh = _fresh_extract_validation(baseline_archive, baseline_hash)
        shutil.rmtree(baseline_repo)

        for target in build_targets:
            target_id = str(target["target_id"])
            state = snapshots[target_id]
            features, requirement_mappings = _features_for_state(
                state, requirement_by_id, state_by_id
            )
            output_contract = target["output_contract"]
            target_name = PurePosixPath(output_contract["target_directory"]).name
            target_root = staging_project / "targets" / target_name
            repo = target_root / ".repo-work"
            _materialize_repository(
                repo,
                project_id=project_id,
                project_title=str(plan.get("project_title") or project_id),
                profile=profile,
                features=features,
            )
            commands = _validate_repository(repo)
            _clean_runtime_files(repo)
            leakage = _audit_repository(repo)
            repo_hash = _tree_hash(repo)
            archive_path = target_root / "pre_repo.zip"
            _zip_repository(repo, archive_path)
            archive_audit = _audit_archive(archive_path)
            fresh_commands = _fresh_extract_validation(archive_path, repo_hash)
            failed_features = [
                item["slug"]
                for item in features
                if (item.get("execution") or {}).get("status") == "FAILED"
            ]
            event_ids, event_types = _flatten_target_events(target)
            manifest = {
                "schema_version": "rq4-code-environment-target-manifest-v1",
                "project_id": project_id,
                "target_id": target_id,
                "before_message_id": target["target_message_id"],
                "repository_classification": "synthetic-executable-pre-state",
                "contract_layer": profile["contract_layer"],
                "web_api_layer": profile["web_api_layer"],
                "active_code_feature_count": len(features),
                "tracked_requirement_count": len(state),
                "temporal_fixture": {
                    "failed_feature_count": len(failed_features),
                    "failed_feature_keys": failed_features,
                },
                "requirements_to_code": requirement_mappings,
                "target_event_ids": event_ids,
                "target_event_types": event_types,
                "target_summary": target.get("target_task"),
                "pre_state_verified_against_gold": True,
                "post_state_verified_against_gold": True,
                "repo_sha256": repo_hash,
                "archive_sha256": _sha256(archive_path),
                "archive_audit": archive_audit,
                "leakage_audit": leakage,
                "source_plan_sha256": _sha256(plan_path),
            }
            _write_json(target_root / "manifest.json", manifest)
            shutil.rmtree(repo)
            target_index.append(manifest)
            validation_records.append(
                {
                    "target_id": target_id,
                    "before_message_id": target["target_message_id"],
                    "commands": commands,
                    "fresh_extraction_commands": fresh_commands,
                    "status": "PASS",
                }
            )

        reports = staging_project / "reports"
        _write_json(reports / "target_index.json", target_index)
        _write_json(
            reports / "source_checksums.json",
            {
                "schema_version": "rq4-code-environment-source-checksums-v1",
                "project_id": project_id,
                "plan_sha256": _sha256(plan_path),
                "sources": plan["project_sources"],
            },
        )
        _write_json(
            reports / "replay_manifest.json",
            {
                "schema_version": "rq4-code-environment-replay-v1",
                "project_id": project_id,
                "event_group_count": len(ledger),
                "event_count": sum(row["event_count"] for row in ledger),
                "build_target_count": len(build_targets),
                "ledger": ledger,
            },
        )
        _write_json(
            reports / "validation_report.json",
            {
                "schema_version": "rq4-code-environment-validation-v1",
                "project_id": project_id,
                "overall": "PASS",
                "construction_policy": "FROM_SCRATCH_NEW_RELEASE_ONLY",
                "baseline": {
                    "commands": baseline_commands,
                    "fresh_extraction_commands": baseline_fresh,
                    "repo_sha256": baseline_hash,
                    "archive_sha256": _sha256(baseline_archive),
                    "archive_audit": baseline_archive_audit,
                    "leakage_audit": baseline_audit,
                },
                "targets": validation_records,
            },
        )
        _write_text(
            reports / "reconstruction_report.md",
            f"# {project_id} RQ4 Code Environment reconstruction\n\n"
            f"- Construction policy: `FROM_SCRATCH_NEW_RELEASE_ONLY`\n"
            f"- Artifact class: `{profile['artifact_class']}`\n"
            f"- Build targets: {len(build_targets)}\n"
            f"- Replayed event groups: {len(ledger)}\n"
            f"- Replayed events: {sum(row['event_count'] for row in ledger)}\n"
            "- Gold pre/post state checks: PASS\n"
            "- Clean build, artifact checks, regression, fresh extraction: PASS\n"
            "- Archive safety and agent-visible leakage audit: PASS\n",
        )
        _write_text(
            staging_project / "README.md",
            f"# {project_id} RQ4 Code Environment\n\n"
            "This project was reconstructed from the frozen new Stage 1/2 release.\n"
            "See `reports/reconstruction_report.md` and `reports/validation_report.json`.\n",
        )
        _write_text(
            staging_project / "tools" / "rebuild.py",
            "from pathlib import Path\nimport subprocess, sys\n"
            "root = Path(__file__).resolve().parents[3]\n"
            f"raise SystemExit(subprocess.call([sys.executable, str(root / 'Code' / 'build_rq4_code_environments.py'), '--project-id', '{project_id}', '--replace'], cwd=root))\n",
        )

        expected_ids = [str(target["target_id"]) for target in build_targets]
        actual_ids = [str(row["target_id"]) for row in target_index]
        if actual_ids != expected_ids:
            raise BuildError(f"{project_id} target index differs from plan")
        if canonical_project.exists():
            shutil.rmtree(canonical_project)
        shutil.move(str(staging_project), str(canonical_project))
        return {
            "project_id": project_id,
            "build_target_count": len(build_targets),
            "event_group_count": len(ledger),
            "status": "PASS",
        }
    except Exception:
        raise


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans-root", type=Path, default=DEFAULT_PLANS_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--project-id", action="append", dest="project_ids")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing canonical project only after staging passes.",
    )
    return parser.parse_args()


def main() -> int:
    args = _args()
    try:
        if args.project_ids:
            project_ids = args.project_ids
        else:
            allowlist = _read_json(ROOT / "Code" / "config" / "rq4_project_allowlist.json")
            project_ids = list(allowlist["project_ids"])
        if not project_ids or len(project_ids) != len(set(project_ids)):
            raise BuildError("project selection must be non-empty and unique")
        args.output_root.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        for project_id in project_ids:
            plan_path = args.plans_root / project_id / "rq4_build_plan.json"
            if not plan_path.is_file():
                raise BuildError(f"project plan is missing: {plan_path}")
            result = _build_project(
                plan_path, args.output_root, replace_existing=args.replace
            )
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        staging_root = args.output_root / ".staging"
        if staging_root.is_dir() and not any(staging_root.iterdir()):
            staging_root.rmdir()
        print(
            json.dumps(
                {
                    "project_count": len(results),
                    "build_target_count": sum(
                        row["build_target_count"] for row in results
                    ),
                    "projects": results,
                    "status": "PASS",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (OSError, KeyError, TypeError, ValueError, BuildError) as exc:
        print(f"RQ4 Code Environment build failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
