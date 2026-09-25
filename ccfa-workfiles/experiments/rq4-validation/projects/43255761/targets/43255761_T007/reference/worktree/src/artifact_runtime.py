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

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _xml_attr(value):
    return escape(str(value), {'"': '&quot;'})


def _value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _style_id(name):
    return re.sub(r"[^A-Za-z0-9]", "", str(name)) or "Style"


def artifact_model():
    return deepcopy(ARTIFACT_MODEL)


def _zip_member(archive, name, content):
    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content.encode("utf-8"))


def _style_xml(style):
    style_id = _style_id(style["name"])
    based_on = style.get("based_on")
    size = re.search(r"\d+(?:\.\d+)?", str(style.get("font_size_pt", 11)))
    half_points = int(float(size.group(0)) * 2) if size else 22
    ppr = []
    if style.get("line_spacing_pt"):
        ppr.append(f'<w:spacing w:line="{int(float(style["line_spacing_pt"]) * 20)}" w:lineRule="exact"/>')
    if style.get("space_after_pt") is not None:
        ppr.append(f'<w:spacing w:after="{int(float(style["space_after_pt"]) * 20)}"/>')
    rpr = [f'<w:sz w:val="{half_points}"/>', f'<w:szCs w:val="{half_points}"/>']
    if style.get("font_family"):
        family = _xml_attr(style["font_family"])
        rpr.append(f'<w:rFonts w:ascii="{family}" w:hAnsi="{family}" w:eastAsia="{family}" w:cs="{family}"/>')
    if style.get("italic"):
        rpr.append("<w:i/><w:iCs/>")
    if style.get("bold"):
        rpr.append("<w:b/><w:bCs/>")
    return (
        f'<w:style w:type="{_xml_attr(style.get("type", "paragraph"))}" w:styleId="{style_id}">'
        f'<w:name w:val="{_xml_attr(style["name"])}"/>'
        + (f'<w:basedOn w:val="{_style_id(based_on)}"/>' if based_on else "")
        + (f'<w:pPr>{"".join(ppr)}</w:pPr>' if ppr else "")
        + f'<w:rPr>{"".join(rpr)}</w:rPr></w:style>'
    )


def _control_xml(control, index):
    label = str(control.get("label") or control.get("title") or control["tag"])
    placeholder = str(control.get("placeholder") or control.get("title") or label)
    tag = str(control["tag"])
    kind = control.get("kind", "text")
    placeholder_id = f"Placeholder{index}"
    if kind == "date":
        type_xml = (
            '<w:date><w:dateFormat w:val="dd/MM/yyyy"/>'
            '<w:lid w:val="da-DK"/><w:storeMappedDataAs w:val="dateTime"/></w:date>'
        )
    elif kind == "rich_text":
        type_xml = ""
    else:
        multiline = ' w:multiLine="1"' if control.get("multiline") else ""
        type_xml = f"<w:text{multiline}/>"
    color = _xml_attr(control.get("placeholder_color", "808080"))
    label_xml = f'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{escape(label)}</w:t></w:r></w:p>'
    control_xml = (
        '<w:sdt><w:sdtPr>'
        f'<w:alias w:val="{_xml_attr(label)}"/><w:tag w:val="{_xml_attr(tag)}"/>'
        f'<w:id w:val="{1000 + index}"/><w:placeholder><w:docPart w:val="{placeholder_id}"/></w:placeholder>'
        f'<w:showingPlcHdr/>{type_xml}</w:sdtPr><w:sdtContent>'
        f'<w:p><w:r><w:rPr><w:color w:val="{color}"/></w:rPr><w:t>{escape(placeholder)}</w:t></w:r></w:p>'
        '</w:sdtContent></w:sdt>'
    )
    glossary = (
        '<w:docPart><w:docPartPr>'
        f'<w:name w:val="{placeholder_id}"/><w:category w:val="General"/>'
        '<w:behaviors><w:behavior w:val="content"/></w:behaviors>'
        '</w:docPartPr><w:docPartBody>'
        f'<w:p><w:r><w:rPr><w:color w:val="{color}"/></w:rPr><w:t>{escape(placeholder)}</w:t></w:r></w:p>'
        '<w:sectPr/></w:docPartBody></w:docPart>'
    )
    return label_xml + control_xml, glossary


def _table_xml(table):
    widths = [int(value) for value in table.get("column_widths_twips", [4500, 4500])]
    rows = table.get("rows", [])
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
    row_xml = []
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            width = widths[min(index, len(widths) - 1)]
            cells.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>'
                '<w:vAlign w:val="center"/><w:tcBorders>'
                '<w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/><w:right w:val="nil"/>'
                '</w:tcBorders></w:tcPr>'
                f'<w:p><w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr><w:r><w:t>{escape(str(value))}</w:t></w:r></w:p></w:tc>'
            )
        row_xml.append("<w:tr>" + "".join(cells) + "</w:tr>")
    return (
        '<w:tbl><w:tblPr><w:tblW w:w="9000" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
        '<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/>'
        '<w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
        '</w:tblPr><w:tblGrid>' + grid + '</w:tblGrid>' + "".join(row_xml) + '</w:tbl>'
    )


def _theme_xml(colors):
    defaults = {
        "dk1": "1F2933", "lt1": "FFFFFF", "dk2": "173F3A", "lt2": "F5F3EE",
        "accent1": "2F6B5F", "accent2": "C9A667", "accent3": "547AA5",
        "accent4": "7D8B8C", "accent5": "8F6F56", "accent6": "6C7A45",
        "hlink": "3659D9", "folHlink": "6B4E9B",
    }
    defaults.update(colors or {})
    entries = []
    for name, value in defaults.items():
        tag = "sysClr" if name in {"dk1", "lt1"} else "srgbClr"
        attrs = f'val="{value}" lastClr="{value}"' if tag == "sysClr" else f'val="{value}"'
        entries.append(f'<a:{name}><a:{tag} {attrs}/></a:{name}>')
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="{A}" name="NXQ Controlled Theme">'
        '<a:themeElements><a:clrScheme name="NXQ Controlled Palette">' + "".join(entries) +
        '</a:clrScheme><a:fontScheme name="NXQ Fonts"><a:majorFont><a:latin typeface="Century Gothic"/>'
        '</a:majorFont><a:minorFont><a:latin typeface="Century Gothic"/></a:minorFont></a:fontScheme>'
        '<a:fmtScheme name="NXQ Format"/></a:themeElements></a:theme>'
    )


def _docx_parts(model, title):
    styles_xml_body = "".join(_style_xml(style) for style in model.get("styles", []))
    body = [f'<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>{escape(title)}</w:t></w:r></w:p>']
    glossary = []
    for index, control in enumerate(model.get("content_controls", []), 1):
        control_xml, glossary_xml = _control_xml(control, index)
        body.append(control_xml)
        glossary.append(glossary_xml)
    for sample in model.get("caption_samples", []):
        body.append(
            f'<w:p><w:pPr><w:pStyle w:val="{_style_id(sample.get("style", "caption text"))}"/></w:pPr>'
            f'<w:r><w:t>{escape(sample["text"])}</w:t></w:r></w:p>'
        )
    for table in model.get("layout_tables", []):
        body.append(f'<w:p><w:r><w:t>{escape(table.get("title", "Layout"))}</w:t></w:r></w:p>')
        body.append(_table_xml(table))
    spacing = model.get("spacing", [])
    for index, item in enumerate(model.get("content", model.get("sections", [])), 1):
        heading = item.get("heading", "Section")
        behavior = item.get("behavior", item.get("key", "section"))
        body.append(
            f'<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:spacing w:before="120" w:after="80"/></w:pPr>'
            f'<w:bookmarkStart w:id="{2000 + index}" w:name="{_xml_attr(behavior)}"/>'
            f'<w:r><w:t>{escape(heading)}</w:t></w:r><w:bookmarkEnd w:id="{2000 + index}"/></w:p>'
        )
        for key, value in sorted((item.get("body") or {}).items()):
            body.append(
                f'<w:p><w:pPr><w:pStyle w:val="NXQContinuousText"/><w:spacing w:after="{0 if spacing else 0}"/></w:pPr>'
                f'<w:r><w:t>{escape(str(key))}: {escape(_value(value))}</w:t></w:r></w:p>'
            )
    body.append('<w:sectPr><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>')
    document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}"><w:body>{"".join(body)}</w:body></w:document>'
    styles = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="{W}">'
        '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Century Gothic" w:hAnsi="Century Gothic"/>'
        '</w:rPr></w:rPrDefault></w:docDefaults>' + styles_xml_body + '</w:styles>'
    )
    settings = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings xmlns:w="{W}">'
        f'<w:themeFontLang w:val="{_xml_attr(model.get("language", "en-US"))}"/></w:settings>'
    )
    controls_contract = "".join(
        f'<control tag="{_xml_attr(item["tag"])}" label="{_xml_attr(item.get("label", item.get("title", item["tag"])))}" '
        f'placeholder="{_xml_attr(item.get("placeholder", item.get("title", "")))}" '
        f'kind="{_xml_attr(item.get("kind", "text"))}" persistent="{str(bool(item.get("persistent", True))).lower()}"/>'
        for item in model.get("content_controls", [])
    )
    help_xml = "".join(
        f'<entry topic="{_xml_attr(item["topic"])}" source="{_xml_attr(item["source"])}">{escape(item["text"])}</entry>'
        for item in model.get("help", [])
    )
    spacing_xml = "".join(
        f'<entry scope="{_xml_attr(item["scope"])}" property="{_xml_attr(item["property"])}">{escape(_value(item["value"]))}</entry>'
        for item in spacing
    )
    contract = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><artifactContract>'
        f'<controls>{controls_contract}</controls><help>{help_xml}</help><spacing>{spacing_xml}</spacing>'
        '</artifactContract>'
    )
    glossary_doc = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:glossaryDocument xmlns:w="{W}">'
        f'<w:docParts>{"".join(glossary)}</w:docParts></w:glossaryDocument>'
    )
    content_types = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
<Override PartName="/word/glossary/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.glossary+xml"/>
<Override PartName="/word/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
</Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
    document_rels = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="../customXml/item1.xml"/>
<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/glossaryDocument" Target="glossary/document.xml"/>
<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>
</Relationships>'''
    return {
        "[Content_Types].xml": content_types,
        "_rels/.rels": rels,
        "word/_rels/document.xml.rels": document_rels,
        "word/document.xml": document,
        "word/styles.xml": styles,
        "word/settings.xml": settings,
        "word/glossary/document.xml": glossary_doc,
        "word/theme/theme1.xml": _theme_xml(model.get("theme_colors")),
        "customXml/item1.xml": contract,
    }


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
        theme = ET.fromstring(archive.read("word/theme/theme1.xml"))
        members = set(archive.namelist())
    ns = {"w": W, "a": A}
    style_details = []
    for style in styles.findall("w:style", ns):
        name = style.find("w:name", ns)
        fonts = style.find("w:rPr/w:rFonts", ns)
        spacing = style.find("w:pPr/w:spacing", ns)
        style_details.append({
            "id": style.attrib.get(f"{{{W}}}styleId"),
            "name": name.attrib.get(f"{{{W}}}val") if name is not None else None,
            "font": fonts.attrib.get(f"{{{W}}}ascii") if fonts is not None else None,
            "italic": style.find("w:rPr/w:i", ns) is not None,
            "line": spacing.attrib.get(f"{{{W}}}line") if spacing is not None else None,
        })
    controls = []
    for control in document.findall(".//w:sdt", ns):
        pr = control.find("w:sdtPr", ns)
        alias = pr.find("w:alias", ns)
        tag = pr.find("w:tag", ns)
        placeholder = pr.find("w:placeholder/w:docPart", ns)
        controls.append({
            "tag": tag.attrib.get(f"{{{W}}}val") if tag is not None else None,
            "label": alias.attrib.get(f"{{{W}}}val") if alias is not None else None,
            "placeholder_part": placeholder.attrib.get(f"{{{W}}}val") if placeholder is not None else None,
            "showing_placeholder": pr.find("w:showingPlcHdr", ns) is not None,
            "multiline": (pr.find("w:text", ns) is not None and pr.find("w:text", ns).attrib.get(f"{{{W}}}multiLine") == "1"),
            "date": pr.find("w:date", ns) is not None,
            "text": "".join(node.text or "" for node in control.findall(".//w:t", ns)),
        })
    color_scheme = theme.find(".//a:clrScheme", ns)
    return {
        "styles": [item["name"] for item in style_details],
        "style_details": style_details,
        "content_controls": [item["tag"] for item in controls],
        "control_details": controls,
        "fields": [item.attrib.get(f"{{{W}}}instr") for item in document.findall(".//w:fldSimple", ns)],
        "spacing": [dict(item.attrib) for item in document.findall(".//w:spacing", ns)],
        "language": settings.find(".//w:themeFontLang", ns).attrib.get(f"{{{W}}}val"),
        "text": [item.text or "" for item in document.findall(".//w:t", ns)],
        "help": [{"topic": item.attrib.get("topic"), "source": item.attrib.get("source"), "text": item.text or ""} for item in contract.findall("./help/entry")],
        "spacing_contract": [{"scope": item.attrib.get("scope"), "property": item.attrib.get("property"), "value": item.text or ""} for item in contract.findall("./spacing/entry")],
        "fixed_layout_tables": len(document.findall('.//w:tblLayout[@w:type="fixed"]', ns)),
        "theme_colors": [node.tag.rsplit("}", 1)[-1] for node in list(color_scheme)] if color_scheme is not None else [],
        "has_glossary": "word/glossary/document.xml" in members,
    }


def _preview(model, title):
    controls = "".join(
        f'<label>{html_escape(item.get("label", item.get("title", item["tag"])))}'
        f'<span data-tag="{html_escape(item["tag"])}">{html_escape(item.get("placeholder", item.get("title", "")))}</span></label>'
        for item in model.get("content_controls", [])
    )
    items = model.get("content", model.get("sections", []))
    body = "".join(
        f'<section data-key="{html_escape(item.get("behavior", item.get("key", "section")))}">'
        f'<h2>{html_escape(item.get("heading", "Section"))}</h2><pre>{html_escape(_value(item.get("body", {})))}</pre></section>'
        for item in items
    )
    return f'<!doctype html><html><head><meta charset="utf-8"><title>{html_escape(title)}</title></head><body><h1>{html_escape(title)}</h1>{controls}{body}</body></html>'


def build_artifacts(output="dist"):
    output = Path(output)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    model = artifact_model()
    if PROJECT["renderer"] != "docx":
        raise ValueError("this reference runtime supports the DOCX artifact contract")
    _write_docx(output / "template.docx", model, PROJECT["title"])
    (output / "template-preview.html").write_text(_preview(model, PROJECT["title"]), encoding="utf-8")
    return output


def parse_artifacts(output="dist"):
    return _parse_docx(Path(output) / "template.docx")


def check_artifacts(output="dist"):
    output = Path(output)
    expected = [output / name.removeprefix("dist/") for name in PROJECT["primary_artifacts"]]
    missing = [str(path) for path in expected if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise RuntimeError(f"missing build artifacts: {missing}")
    parsed = parse_artifacts(output)
    if not parsed["styles"] or not parsed["has_glossary"]:
        raise RuntimeError("OOXML artifact is missing styles or placeholder glossary")
    if len(parsed["content_controls"]) != len(ARTIFACT_MODEL.get("content_controls", [])):
        raise RuntimeError("OOXML artifact does not preserve the content-control model")
    return {
        "renderer": "docx",
        "artifact_count": len(expected),
        "feature_count": len(FEATURES),
        "domain_model": ARTIFACT_MODEL["schema"],
    }

