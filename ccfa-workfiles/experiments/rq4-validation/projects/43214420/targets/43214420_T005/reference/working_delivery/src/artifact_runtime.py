from __future__ import annotations

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
from kicad_reference import build_kicad_files, parse_kicad_files, validate_kicad_model

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
        build_kicad_files(model, output)
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
    if renderer == "kicad": return parse_kicad_files(output)
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
    if renderer == "kicad":
        validate_kicad_model(ARTIFACT_MODEL, parsed)
    if renderer in {"docx", "report"} and not parsed["styles"]:
        raise RuntimeError("OOXML artifact has no style definitions")
    if renderer == "report" and len(parsed["pdf_coordinates"]) != len(ARTIFACT_MODEL["pdf_coordinates"]):
        raise RuntimeError("PDF layout does not preserve the coordinate model")
    return {"renderer": renderer, "artifact_count": len(expected), "feature_count": len(FEATURES), "domain_model": ARTIFACT_MODEL["schema"]}
