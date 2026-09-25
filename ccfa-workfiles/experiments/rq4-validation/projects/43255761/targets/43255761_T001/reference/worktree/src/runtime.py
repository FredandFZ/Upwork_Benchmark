from __future__ import annotations

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


# RQ4_ARTIFACT_DOMAIN_RUNTIME
from artifact_runtime import (
    artifact_model, build_artifacts, check_artifacts, parse_artifacts
)
build = build_artifacts
check = check_artifacts
