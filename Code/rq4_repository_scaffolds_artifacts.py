from __future__ import annotations

"""Agent-visible artifact contracts for the non-Web RQ4 repositories.

The module is used while a repository is being materialized.  It derives a
deterministic, editable domain model from the *current* feature snapshot and
writes a self-contained stdlib implementation into that repository.  The
generated repository neither imports this host module nor contains requirement,
state, event, Gold, or validator identifiers.
"""

from collections.abc import Mapping
import json
from pathlib import Path
import pprint
import re
from typing import Any


SUPPORTED_PROJECTS = {
    "43214420": "kicad",
    "43255761": "docx",
    "44036410": "report",
}
_RUNTIME_MARKER = "# RQ4_ARTIFACT_DOMAIN_RUNTIME\n"
_PRIVATE_ID = re.compile(r"(?:REQ_[A-Z0-9_]+|(?:STATE|EVENT)_[A-Z0-9_]+|_[SE]\d{3}\b)")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in sorted(value.items()):
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_walk(child, path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            rows.extend(_walk(child, f"{prefix}[{index}]"))
    else:
        rows.append((prefix, value))
    return rows


def _slug(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or fallback


def _text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _feature_rows(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    original_payload = json.dumps(_plain(features), ensure_ascii=False, sort_keys=True)
    match = _PRIVATE_ID.search(original_payload)
    if match:
        raise ValueError(f"private construction identifier is not allowed: {match.group(0)}")
    rows: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, original in enumerate(features, 1):
        feature = _plain(original)
        slug = _slug(str(feature.get("slug") or feature.get("title") or ""), f"feature-{index}")
        while slug in used:
            slug = f"{slug}-{index}"
        used.add(slug)
        rows.append(
            {
                "slug": slug,
                "title": str(feature.get("title") or slug.replace("-", " ").title()),
                "attributes": feature.get("attributes") if isinstance(feature.get("attributes"), dict) else {},
                "components": list(feature.get("components") or []),
                "contexts": list(feature.get("contexts") or []),
                "execution": feature.get("execution") if isinstance(feature.get("execution"), dict) else {},
            }
        )
    return rows


def _named_values(value: Any, wanted: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() == wanted.lower():
                found.append(child)
            found.extend(_named_values(child, wanted))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.extend(_named_values(child, wanted))
    return found


def _signal_names(attributes: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key, value in _walk(attributes):
        lower = key.lower()
        if not any(word in lower for word in ("signal", "rail", "pinout", "pin_order", "net")):
            continue
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if not isinstance(candidate, (str, int, float)):
                continue
            for token in re.findall(r"(?:[A-Za-z][A-Za-z0-9_+.-]{0,31}|\d+(?:\.\d+)?V\w*)", str(candidate)):
                if token.upper() in {"AND", "THE", "WITH", "FROM", "PIN", "BOARD"}:
                    continue
                if token.upper() == token or re.fullmatch(r"\d+(?:\.\d+)?V", token, re.I):
                    values.append(token.upper().replace("+", "_P"))
    return list(dict.fromkeys(values))


def _component_prefix(title: str, attributes: Mapping[str, Any]) -> str:
    haystack = (title + " " + " ".join(str(key) for key in attributes)).lower()
    for word, prefix in (
        ("connector", "J"),
        ("resistor", "R"),
        ("capacitor", "C"),
        ("buzzer", "BZ"),
        ("led", "D"),
        ("diode", "D"),
        ("switch", "SW"),
        ("sensor", "U"),
    ):
        if word in haystack:
            return prefix
    return "U"


def _footprint(attributes: Mapping[str, Any], prefix: str) -> str:
    flat = dict(_walk(attributes))
    for key, value in flat.items():
        if any(word in key.lower() for word in ("footprint", "package", "connector_type")):
            return re.sub(r"[^A-Za-z0-9_.:+-]+", "_", str(value))[:80] or "Generic"
    return {"J": "Connector_Generic", "R": "R_0603", "C": "C_0603", "D": "LED_SMD"}.get(prefix, "Package_Generic")


def _kicad_model(features: list[dict[str, Any]]) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    nets: dict[str, list[str]] = {}
    counters: dict[str, int] = {}
    width, height = 100.0, 80.0
    markings: list[str] = []
    for index, feature in enumerate(features):
        attributes = feature["attributes"]
        for key, value in _walk(attributes):
            if key.endswith("board_dimensions_mm.width") and isinstance(value, (int, float)):
                width = float(value)
            elif key.endswith("board_dimensions_mm.height") and isinstance(value, (int, float)):
                height = float(value)
            elif "qr_code" in key or "marking" in key or "pin_label" in key:
                markings.append(f"{feature['slug']}:{key}={_text(value)}")
        prefix = _component_prefix(feature["title"], attributes)
        counters[prefix] = counters.get(prefix, 0) + 1
        reference = f"{prefix}{counters[prefix]}"
        signals = _signal_names(attributes)
        pins: list[dict[str, str]] = []
        for pin_index, signal in enumerate(signals[:16], 1):
            pins.append({"number": str(pin_index), "net": signal})
            nets.setdefault(signal, []).append(f"{reference}.{pin_index}")
        components.append(
            {
                "reference": reference,
                "value": feature["title"],
                "footprint": _footprint(attributes, prefix),
                "at_mm": [round(12 + (index % 8) * 11.0, 2), round(12 + (index // 8) * 10.0, 2)],
                "rotation_deg": 0,
                "pins": pins,
                "behavior": feature["slug"],
                "properties": attributes,
            }
        )
    return {
        "schema": "artifact-kicad-v1",
        "components": components,
        "nets": [{"name": name, "members": members} for name, members in sorted(nets.items())],
        "footprints": [
            {"reference": item["reference"], "library_id": item["footprint"], "at_mm": item["at_mm"], "rotation_deg": item["rotation_deg"]}
            for item in components
        ],
        "geometry": {
            "units": "mm",
            "board_size": {"width": width, "height": height},
            "outline": [[0.0, 0.0], [width, 0.0], [width, height], [0.0, height], [0.0, 0.0]],
            "markings": list(dict.fromkeys(markings)),
        },
    }


def _first_matching(attributes: Mapping[str, Any], words: tuple[str, ...]) -> list[tuple[str, Any]]:
    return [(key, value) for key, value in _walk(attributes) if any(word in key.lower() for word in words)]


def _docx_model(features: list[dict[str, Any]]) -> dict[str, Any]:
    styles: dict[str, dict[str, Any]] = {
        "Normal": {"type": "paragraph", "font_size_pt": 11, "based_on": None},
        "Title": {"type": "paragraph", "font_size_pt": 40, "based_on": "Normal"},
    }
    controls: dict[str, dict[str, Any]] = {}
    fields: dict[str, dict[str, Any]] = {}
    help_entries: list[dict[str, str]] = []
    spacing: list[dict[str, Any]] = []
    language = "en-US"
    for feature in features:
        attrs = feature["attributes"]
        flat = _walk(attrs)
        prefixes = [str(value) for key, value in flat if "style_prefix" in key.lower()]
        if _first_matching(attrs, ("style", "typography", "font_size")):
            name = f"{prefixes[0] + ' ' if prefixes else ''}{feature['title']}".strip()
            size = next((value for key, value in flat if "font_size" in key.lower()), 11)
            styles[name] = {"type": "paragraph", "font_size_pt": size, "based_on": "Normal", "source": feature["slug"]}
        for editable_fields in _named_values(attrs, "editable_fields"):
            if isinstance(editable_fields, list):
                for field in editable_fields:
                    name = _slug(str(field), "editable-field")
                    controls[name] = {"tag": name, "title": str(field).replace("_", " ").title(), "kind": "text", "source": feature["slug"]}
        for key, value in flat:
            lower = key.lower()
            if "language" in lower and isinstance(value, str):
                language = "da-DK" if "danish" in value.lower() else value
            if any(word in lower for word in ("content_control", "interactive_field", "placeholder")):
                name = _slug(key.split(".")[-1], "control")
                controls[name] = {"tag": name, "title": _text(value), "kind": "text", "source": feature["slug"]}
            if lower.endswith("_field") or lower.endswith("_field_format"):
                name = _slug(key.split(".")[-1], "field")
                fields[name] = {"instruction": f"DOCPROPERTY {name}", "display": _text(value), "source": feature["slug"]}
            if any(word in lower for word in ("help", "guidance", "instruction")):
                help_entries.append({"topic": feature["title"], "text": _text(value), "source": feature["slug"]})
            if any(word in lower for word in ("spacing", "padding", "margin", "indent")):
                spacing.append({"scope": feature["slug"], "property": key, "value": _plain(value)})
    return {
        "schema": "artifact-docx-v1",
        "language": language,
        "styles": [{"name": name, **definition} for name, definition in styles.items()],
        "content_controls": list(controls.values()),
        "fields": list(fields.values()),
        "help": help_entries,
        "spacing": spacing,
        "content": [{"heading": item["title"], "body": item["attributes"], "behavior": item["slug"]} for item in features],
    }


def _variant_codes(features: list[dict[str, Any]]) -> list[str]:
    codes: list[str] = []
    for feature in features:
        for variant_codes in _named_values(feature["attributes"], "variant_codes"):
            if isinstance(variant_codes, list):
                codes.extend(str(item) for item in variant_codes)
        for key, value in _walk(feature["attributes"]):
            codes.extend(re.findall(r"DX\d{2}", key.upper()))
            if isinstance(value, str):
                codes.extend(re.findall(r"DX[- ]?\d{2}", value.upper()))
    return list(dict.fromkeys(code.replace("-", "").replace(" ", "") for code in codes))


def _report_model(features: list[dict[str, Any]]) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    coordinates: list[dict[str, Any]] = []
    assets: list[str] = []
    for index, feature in enumerate(features):
        page = 1 + index // 4
        slot = index % 4
        section = {
            "key": feature["slug"],
            "heading": feature["title"],
            "body": feature["attributes"],
            "contexts": feature["contexts"],
        }
        sections.append(section)
        coordinates.append({"section": feature["slug"], "page": page, "x_pt": 54, "y_pt": 738 - slot * 168, "width_pt": 504, "height_pt": 144})
        for package_contents in _named_values(feature["attributes"], "package_contents"):
            if isinstance(package_contents, list):
                assets.extend(str(item) for item in package_contents)
    variants = _variant_codes(features)
    document_model = _docx_model(features)
    return {
        "schema": "artifact-report-v1",
        "language": document_model["language"],
        "styles": document_model["styles"],
        "content_controls": document_model["content_controls"],
        "fields": document_model["fields"],
        "help": document_model["help"],
        "spacing": document_model["spacing"],
        "sections": sections,
        "layout": {"page_size_pt": [612, 792], "margins_pt": [54, 54, 54, 54], "section_boxes": coordinates},
        "package_manifest": {
            "variants": variants,
            "assets": list(dict.fromkeys(assets)),
            "deliverables": ["security-report.docx", "security-report.pdf", "report-preview.html", "report-package.json"],
        },
        "pdf_coordinates": coordinates,
    }


ARTIFACT_RUNTIME_SOURCE = r"""from __future__ import annotations

from copy import deepcopy
from html import escape as html_escape
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import zipfile

from artifact_model import ARTIFACT_MODEL
from current_state import FEATURES, PROJECT

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _xml_attr(value):
    return escape(str(value), {'"': '&quot;'})


def artifact_model():
    return deepcopy(ARTIFACT_MODEL)


def _value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _zip_member(archive, name, content):
    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content.encode("utf-8"))


def _docx_parts(model, title):
    styles = []
    for style in model.get("styles", []):
        style_id = re.sub(r"[^A-Za-z0-9]", "", style["name"]) or "Style"
        size = re.search(r"\d+(?:\.\d+)?", str(style.get("font_size_pt", 11)))
        half_points = int(float(size.group(0)) * 2) if size else 22
        styles.append(f'<w:style w:type="paragraph" w:styleId="{_xml_attr(style_id)}"><w:name w:val="{_xml_attr(style["name"])}"/><w:rPr><w:sz w:val="{half_points}"/></w:rPr></w:style>')
    body = [f'<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>{escape(title)}</w:t></w:r></w:p>']
    for control in model.get("content_controls", []):
        body.append(f'<w:sdt><w:sdtPr><w:alias w:val="{_xml_attr(control["title"])}"/><w:tag w:val="{_xml_attr(control["tag"])}"/></w:sdtPr><w:sdtContent><w:p><w:r><w:t>{escape(control["title"])}</w:t></w:r></w:p></w:sdtContent></w:sdt>')
    for field in model.get("fields", []):
        body.append(f'<w:p><w:fldSimple w:instr="{_xml_attr(field["instruction"])}"><w:r><w:t>{escape(field["display"])}</w:t></w:r></w:fldSimple></w:p>')
    spacing = model.get("spacing", [])
    for item in model.get("content", model.get("sections", [])):
        heading = item.get("heading", "Section")
        behavior = item.get("behavior", item.get("key", "section"))
        body.append(f'<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:spacing w:before="120" w:after="80"/></w:pPr><w:bookmarkStart w:id="0" w:name="{_xml_attr(behavior)}"/><w:r><w:t>{escape(heading)}</w:t></w:r><w:bookmarkEnd w:id="0"/></w:p>')
        for key, value in sorted((item.get("body") or {}).items()):
            body.append(f'<w:p><w:pPr><w:spacing w:after="{120 if spacing else 0}"/></w:pPr><w:r><w:t>{escape(str(key))}: {escape(_value(value))}</w:t></w:r></w:p>')
    document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"><w:body>{"".join(body)}<w:sectPr/></w:body></w:document>'''
    styles_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">{"".join(styles)}</w:styles>'''
    settings = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="{W}"><w:themeFontLang w:val="{_xml_attr(model.get("language", "en-US"))}"/></w:settings>'''
    help_xml = "".join(f'<entry topic="{_xml_attr(item["topic"])}" source="{_xml_attr(item["source"])}">{escape(item["text"])}</entry>' for item in model.get("help", []))
    spacing_xml = "".join(f'<entry scope="{_xml_attr(item["scope"])}" property="{_xml_attr(item["property"])}">{escape(_value(item["value"]))}</entry>' for item in model.get("spacing", []))
    contract_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<artifactContract><help>{help_xml}</help><spacing>{spacing_xml}</spacing></artifactContract>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
</Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'''
    document_rels = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="../customXml/item1.xml"/></Relationships>'''
    return {"[Content_Types].xml": content_types, "_rels/.rels": rels, "word/_rels/document.xml.rels": document_rels, "word/document.xml": document, "word/styles.xml": styles_xml, "word/settings.xml": settings, "customXml/item1.xml": contract_xml}


def _write_docx(path, model, title):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in _docx_parts(model, title).items():
            _zip_member(archive, name, content)


def _parse_docx(path):
    with zipfile.ZipFile(path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        styles = ET.fromstring(archive.read("word/styles.xml"))
        settings = ET.fromstring(archive.read("word/settings.xml"))
        contract = ET.fromstring(archive.read("customXml/item1.xml"))
    ns = {"w": W}
    return {
        "styles": [item.attrib.get(f"{{{W}}}val") for item in styles.findall("w:style/w:name", ns)],
        "content_controls": [item.attrib.get(f"{{{W}}}val") for item in document.findall(".//w:sdtPr/w:tag", ns)],
        "fields": [item.attrib.get(f"{{{W}}}instr") for item in document.findall(".//w:fldSimple", ns)],
        "spacing": [dict(item.attrib) for item in document.findall(".//w:spacing", ns)],
        "language": (settings.find(".//w:themeFontLang", ns).attrib.get(f"{{{W}}}val") if settings.find(".//w:themeFontLang", ns) is not None else None),
        "text": [item.text or "" for item in document.findall(".//w:t", ns)],
        "help": [{"topic": item.attrib.get("topic"), "source": item.attrib.get("source"), "text": item.text or ""} for item in contract.findall("./help/entry")],
        "spacing_contract": [{"scope": item.attrib.get("scope"), "property": item.attrib.get("property"), "value": item.text or ""} for item in contract.findall("./spacing/entry")],
    }


def _kicad_text(model):
    symbols = []
    footprints = []
    net_lookup = {net["name"]: index + 1 for index, net in enumerate(model["nets"])}
    for component in model["components"]:
        x, y = component["at_mm"]
        symbols.append(f'  (symbol (lib_id "Generated:Component") (at {x} {y} {component["rotation_deg"]}) (property "Reference" "{component["reference"]}") (property "Value" "{component["value"].replace(chr(34), chr(39))}") (property "Footprint" "{component["footprint"]}"))')
        pads = " ".join(f'(pad "{pin["number"]}" thru_hole circle (at 0 {int(pin["number"])-1}) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask") (net {net_lookup.get(pin["net"], 0)} "{pin["net"]}"))' for pin in component["pins"])
        footprints.append(f'  (footprint "Generated:{component["footprint"]}" (layer "F.Cu") (at {x} {y} {component["rotation_deg"]}) (property "Reference" "{component["reference"]}" (at 0 -2 0) (layer "F.SilkS")) {pads})')
    schematic = '(kicad_sch (version 20231120) (generator rq4_artifact)\n  (uuid 00000000-0000-0000-0000-000000000001)\n  (paper "A4")\n' + "\n".join(symbols) + '\n  (sheet_instances (path "/" (page "1")))\n)\n'
    nets = "\n".join(f'  (net {index + 1} "{net["name"]}")' for index, net in enumerate(model["nets"]))
    points = model["geometry"]["outline"]
    outline = "\n".join(f'  (gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (stroke (width 0.05) (type default)) (layer "Edge.Cuts"))' for a, b in zip(points, points[1:]))
    pcb = '(kicad_pcb (version 20240108) (generator rq4_artifact)\n  (general (thickness 1.6))\n  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (37 "F.SilkS" user "f.silkscreen") (44 "Edge.Cuts" user))\n' + nets + "\n" + "\n".join(footprints) + "\n" + outline + "\n)\n"
    return schematic, pcb


def _parse_kicad(output):
    schematic = (output / "design.kicad_sch").read_text(encoding="utf-8")
    pcb = (output / "design.kicad_pcb").read_text(encoding="utf-8")
    references = re.findall(r'\(property "Reference" "([^"]+)"', schematic)
    footprints = re.findall(r'\(footprint "Generated:([^"]+)"', pcb)
    nets = []
    seen_nets = set()
    for number, name in re.findall(r'\(net (\d+) "([^"]+)"\)', pcb):
        if (number, name) not in seen_nets:
            seen_nets.add((number, name)); nets.append({"id": int(number), "name": name})
    lines = [[float(x1), float(y1), float(x2), float(y2)] for x1, y1, x2, y2 in re.findall(r'\(gr_line \(start ([\d.-]+) ([\d.-]+)\) \(end ([\d.-]+) ([\d.-]+)\)', pcb)]
    def balanced(text):
        depth = 0; quoted = False; escaped = False
        for character in text:
            if escaped: escaped = False; continue
            if character == "\\" and quoted: escaped = True; continue
            if character == '"': quoted = not quoted; continue
            if not quoted and character == "(": depth += 1
            elif not quoted and character == ")":
                depth -= 1
                if depth < 0: return False
        return depth == 0 and not quoted
    return {"components": references, "footprints": footprints, "nets": nets, "geometry_lines": lines, "balanced": balanced(schematic) and balanced(pcb)}


def _pdf_bytes(model, title):
    commands = []
    coordinates = model.get("pdf_coordinates", [])
    section_by_key = {item["key"]: item for item in model.get("sections", [])}
    for box in coordinates:
        section = section_by_key.get(box["section"], {})
        line = section.get("heading", box["section"])
        safe = line.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f'BT /F1 11 Tf {box["x_pt"]} {box["y_pt"]} Td ({safe}) Tj ET')
    stream = "\n".join(commands).encode("latin-1")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>", b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data)); data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data); data.extend(f"xref\n0 {len(objects)+1}\n".encode()); data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]: data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def _parse_pdf_coordinates(path):
    text = path.read_bytes().decode("latin-1")
    return [{"x_pt": float(x), "y_pt": float(y), "text": value.replace("\\(", "(").replace("\\)", ")")} for x, y, value in re.findall(r'([\d.-]+) ([\d.-]+) Td \((.*?)\) Tj', text)]


def _preview(model, title):
    items = model.get("content", model.get("sections", []))
    body = "".join(f'<section data-key="{html_escape(item.get("behavior", item.get("key", "section")))}"><h2>{html_escape(item.get("heading", "Section"))}</h2><pre>{html_escape(_value(item.get("body", {})))}</pre></section>' for item in items)
    return f'<!doctype html><html><head><meta charset="utf-8"><title>{html_escape(title)}</title></head><body><h1>{html_escape(title)}</h1>{body}</body></html>'


def build_artifacts(output="dist"):
    output = Path(output)
    if output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True)
    model = artifact_model()
    renderer = PROJECT["renderer"]
    if renderer == "kicad":
        schematic, pcb = _kicad_text(model)
        (output / "design.kicad_sch").write_text(schematic, encoding="utf-8")
        (output / "design.kicad_pcb").write_text(pcb, encoding="utf-8")
        (output / "design-summary.txt").write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif renderer == "docx":
        _write_docx(output / "template.docx", model, PROJECT["title"])
        (output / "template-preview.html").write_text(_preview(model, PROJECT["title"]), encoding="utf-8")
    elif renderer == "report":
        _write_docx(output / "security-report.docx", model, PROJECT["title"])
        (output / "security-report.pdf").write_bytes(_pdf_bytes(model, PROJECT["title"]))
        (output / "report-preview.html").write_text(_preview(model, PROJECT["title"]), encoding="utf-8")
        (output / "report-package.json").write_text(json.dumps(model["package_manifest"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        raise ValueError(f"unsupported artifact renderer: {renderer}")
    return output


def parse_artifacts(output="dist"):
    output = Path(output)
    renderer = PROJECT["renderer"]
    if renderer == "kicad": return _parse_kicad(output)
    if renderer == "docx": return _parse_docx(output / "template.docx")
    if renderer == "report":
        result = _parse_docx(output / "security-report.docx")
        result["pdf_coordinates"] = _parse_pdf_coordinates(output / "security-report.pdf")
        result["package_manifest"] = json.loads((output / "report-package.json").read_text(encoding="utf-8"))
        return result
    raise ValueError(f"unsupported artifact renderer: {renderer}")


def check_artifacts(output="dist"):
    output = Path(output)
    expected = [output / name.removeprefix("dist/") for name in PROJECT["primary_artifacts"]]
    missing = [str(path) for path in expected if not path.is_file() or path.stat().st_size == 0]
    if missing: raise RuntimeError(f"missing build artifacts: {missing}")
    parsed = parse_artifacts(output)
    renderer = PROJECT["renderer"]
    if renderer == "kicad" and (not parsed["balanced"] or len(parsed["components"]) != len(ARTIFACT_MODEL["components"])):
        raise RuntimeError("KiCad artifacts do not preserve the component model")
    if renderer in {"docx", "report"} and not parsed["styles"]:
        raise RuntimeError("OOXML artifact has no style definitions")
    if renderer == "report" and len(parsed["pdf_coordinates"]) != len(ARTIFACT_MODEL["pdf_coordinates"]):
        raise RuntimeError("PDF layout does not preserve the coordinate model")
    return {"renderer": renderer, "artifact_count": len(expected), "feature_count": len(FEATURES), "domain_model": ARTIFACT_MODEL["schema"]}
"""


INSPECT_SCRIPT = '''from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_runtime import parse_artifacts

print(json.dumps(parse_artifacts(ROOT / "dist"), ensure_ascii=False, indent=2))
'''


REPOSITORY_TEST_SOURCE = '''from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from artifact_model import ARTIFACT_MODEL
from artifact_runtime import build_artifacts, check_artifacts, parse_artifacts


class ArtifactContractTest(unittest.TestCase):
    def test_domain_model_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            build_artifacts(directory)
            parsed = parse_artifacts(directory)
            checked = check_artifacts(directory)
            self.assertEqual(checked["domain_model"], ARTIFACT_MODEL["schema"])
            self.assertIsInstance(parsed, dict)


if __name__ == "__main__":
    unittest.main()
'''


def augment_artifact_repository(
    destination: Path,
    project_id: str,
    features: list[dict[str, Any]],
    profile: Mapping[str, Any],
) -> None:
    """Add a deterministic artifact model and generation/parsing API.

    Unsupported projects are intentionally left unchanged so the builder can
    call this function for every repository.  For supported projects, a
    profile/project mismatch is rejected rather than silently emitting the
    wrong artifact type.
    """

    project_id = str(project_id)
    if project_id not in SUPPORTED_PROJECTS:
        return
    destination = Path(destination)
    if not destination.is_dir():
        raise FileNotFoundError(f"repository destination does not exist: {destination}")
    renderer = str(profile.get("renderer") or "")
    expected_renderer = SUPPORTED_PROJECTS[project_id]
    if renderer != expected_renderer:
        raise ValueError(
            f"project {project_id} requires renderer {expected_renderer!r}, got {renderer!r}"
        )

    rows = _feature_rows(features)
    if renderer == "kicad":
        model = _kicad_model(rows)
    elif renderer == "docx":
        model = _docx_model(rows)
    else:
        model = _report_model(rows)

    model_source = (
        '"""Editable current artifact state used by the deterministic generator."""\n\n'
        "ARTIFACT_MODEL = "
        + pprint.pformat(model, sort_dicts=True, width=100)
        + "\n"
    )
    _write_text(destination / "src" / "artifact_model.py", model_source)
    _write_text(destination / "src" / "artifact_runtime.py", ARTIFACT_RUNTIME_SOURCE)
    _write_text(destination / "scripts" / "inspect_artifacts.py", INSPECT_SCRIPT)
    _write_text(destination / "tests" / "test_artifact_contract.py", REPOSITORY_TEST_SOURCE)

    surface_map = {
        "kicad": [
            "components.reference/value/pins",
            "nets.name/members",
            "footprints.library_id/position/rotation",
            "geometry.board_size/outline/markings",
        ],
        "docx": [
            "styles.name/type/font_size",
            "content_controls.tag/title/kind",
            "fields.instruction/display",
            "help.topic/text",
            "spacing.scope/property/value",
            "ooxml.word/document.xml",
            "ooxml.word/styles.xml",
            "ooxml.word/settings.xml",
        ],
        "report": [
            "sections.key/heading/body/contexts",
            "layout.page_size/margins/section_boxes",
            "package_manifest.variants/assets/deliverables",
            "pdf_coordinates.page/x/y/width/height",
            "ooxml.word/document.xml",
        ],
    }
    behavior_contract = {
        "schema_version": "artifact-behavior-contract-v1",
        "renderer": renderer,
        "deterministic": True,
        "network_required": False,
        "editable_model": "src/artifact_model.py:ARTIFACT_MODEL",
        "entrypoints": {
            "build": "artifact_runtime.build_artifacts(output)",
            "check": "artifact_runtime.check_artifacts(output)",
            "parse": "artifact_runtime.parse_artifacts(output)",
            "inspect_cli": "python scripts/inspect_artifacts.py",
        },
        "stable_artifacts": list(profile.get("primary_artifacts") or []),
        "observable_surfaces": surface_map[renderer],
    }
    _write_text(
        destination / "behavior_contract.json",
        json.dumps(behavior_contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )

    runtime_path = destination / "src" / "runtime.py"
    runtime = runtime_path.read_text(encoding="utf-8") if runtime_path.exists() else ""
    if _RUNTIME_MARKER not in runtime:
        runtime += (
            "\n\n"
            + _RUNTIME_MARKER
            + "from artifact_runtime import (\n"
            + "    artifact_model, build_artifacts, check_artifacts, parse_artifacts\n"
            + ")\n"
            + "build = build_artifacts\n"
            + "check = check_artifacts\n"
        )
        _write_text(runtime_path, runtime)

    readme_path = destination / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    heading = "## Structured artifact contract"
    if heading not in readme:
        readme += (
            "\n"
            + heading
            + "\n\nEdit `src/artifact_model.py`, build the repository, then inspect the "
            + "generated structure with `python scripts/inspect_artifacts.py`.\n"
        )
        _write_text(readme_path, readme)


__all__ = ["augment_artifact_repository"]
