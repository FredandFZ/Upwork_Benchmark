from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable
import xml.etree.ElementTree as ET
import zipfile


SCHEMA_VERSION = "rq4-deterministic-validator-result-v1"
W_URI = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_URI}}}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


class CandidateFailure(RuntimeError):
    pass


class HarnessFault(RuntimeError):
    pass


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise CandidateFailure(message)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _val(node: ET.Element | None, name: str = "val") -> str | None:
    return node.get(W + name) if node is not None else None


def _safe_env() -> dict[str, str]:
    keep = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "NO_PROXY": "*"})
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    return env


def _run(command: list[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "cwd": cwd, "env": _safe_env(), "text": True,
        "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "timeout": timeout,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    try:
        return subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise HarnessFault(f"command timed out after {timeout}s: {command[0]}") from exc
    except OSError as exc:
        raise HarnessFault(f"cannot launch {command[0]}: {exc}") from exc


def _repo(path: Path) -> Path:
    path = path.resolve()
    if not path.is_dir() or not (path / "scripts" / "build.py").is_file():
        raise HarnessFault("repository is missing scripts/build.py")
    return path


def _build(repo: Path) -> list[dict[str, Any]]:
    checks = []
    for test_id, script in (("BUILD-001", "build.py"), ("BUILD-002", "check.py")):
        process = _run([sys.executable, str(repo / "scripts" / script)], repo)
        checks.append({"test_id": test_id, "exit_code": process.returncode})
        if process.returncode != 0:
            raise CandidateFailure(f"{script} failed: {(process.stderr or process.stdout)[-1600:]}")
    path = repo / "dist" / "template.docx"
    if not path.is_file() or path.stat().st_size == 0:
        raise CandidateFailure("missing built artifact dist/template.docx")
    return checks


def _regression(repo: Path) -> list[dict[str, Any]]:
    process = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], repo)
    if process.returncode != 0:
        raise CandidateFailure(f"repository regression tests failed: {(process.stderr or process.stdout)[-1800:]}")
    return [{"test_id": "REG-001", "exit_code": 0}]


def _docx_parts(path: Path) -> dict[str, bytes]:
    if not path.is_file():
        raise CandidateFailure(f"missing DOCX: {path}")
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise CandidateFailure("DOCX contains a corrupt ZIP member")
            parts: dict[str, bytes] = {}
            total = 0
            for info in archive.infolist():
                member = PurePosixPath(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise CandidateFailure("DOCX contains an unsafe ZIP member")
                total += info.file_size
                if total > 64 * 1024 * 1024:
                    raise CandidateFailure("DOCX uncompressed content exceeds 64 MiB")
                if not info.is_dir():
                    parts[info.filename] = archive.read(info)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CandidateFailure(f"DOCX cannot be opened: {exc}") from exc
    for required in ("word/document.xml", "word/styles.xml"):
        if required not in parts:
            raise CandidateFailure(f"DOCX omits {required}")
    return parts


def _xml(parts: dict[str, bytes], name: str) -> ET.Element:
    if name not in parts:
        raise CandidateFailure(f"DOCX omits {name}")
    try:
        return ET.fromstring(parts[name])
    except ET.ParseError as exc:
        raise CandidateFailure(f"malformed OOXML in {name}: {exc}") from exc


def _docx(repo: Path) -> tuple[dict[str, bytes], ET.Element, ET.Element]:
    parts = _docx_parts(repo / "dist" / "template.docx")
    return parts, _xml(parts, "word/document.xml"), _xml(parts, "word/styles.xml")


def _write_docx(path: Path, parts: dict[str, bytes], document: ET.Element) -> None:
    changed = dict(parts)
    changed["word/document.xml"] = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(changed):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, changed[name])


def _interactive(document: ET.Element) -> list[ET.Element]:
    result = []
    for sdt in document.findall(".//" + W + "sdt"):
        properties = sdt.find(W + "sdtPr")
        if properties is None:
            continue
        if properties.find(W + "group") is not None or properties.find(W + "docPartObj") is not None:
            continue
        result.append(sdt)
    return result


def _tag(sdt: ET.Element) -> str:
    properties = sdt.find(W + "sdtPr")
    return _norm(_val(properties.find(W + "tag")) if properties is not None else None)


def _alias(sdt: ET.Element) -> str:
    properties = sdt.find(W + "sdtPr")
    return _norm(_val(properties.find(W + "alias")) if properties is not None else None)


def _direct_text(sdt: ET.Element) -> str:
    content = sdt.find(W + "sdtContent")
    return _norm(" ".join((node.text or "") for node in content.findall(".//" + W + "t"))) if content is not None else ""


def _placeholder_name(sdt: ET.Element) -> str:
    properties = sdt.find(W + "sdtPr")
    placeholder = properties.find(W + "placeholder") if properties is not None else None
    doc_part = placeholder.find(W + "docPart") if placeholder is not None else None
    return _norm(_val(doc_part))


def _glossary(parts: dict[str, bytes]) -> dict[str, str]:
    if "word/glossary/document.xml" not in parts:
        return {}
    root = _xml(parts, "word/glossary/document.xml")
    result = {}
    for part in root.findall(".//" + W + "docPart"):
        name = part.find("./" + W + "docPartPr/" + W + "name")
        key = _norm(_val(name))
        text = _norm(" ".join((node.text or "") for node in part.findall(".//" + W + "docPartBody//" + W + "t")))
        if key:
            result[key] = text
    return result


def _instruction(sdt: ET.Element, glossary: dict[str, str]) -> str:
    direct = _direct_text(sdt)
    return direct or glossary.get(_placeholder_name(sdt), "")


def _mapping(controls: list[ET.Element], getter: Callable[[ET.Element], str]) -> dict[str, str]:
    return {_tag(control): getter(control) for control in controls}


def _replace_content(sdt: ET.Element, paragraphs: list[str]) -> None:
    content = sdt.find(W + "sdtContent")
    if content is None:
        content = ET.SubElement(sdt, W + "sdtContent")
    for child in list(content):
        content.remove(child)
    for text in paragraphs:
        paragraph = ET.SubElement(content, W + "p")
        run = ET.SubElement(paragraph, W + "r")
        node = ET.SubElement(run, W + "t")
        node.set(XML_SPACE, "preserve")
        node.text = text


def _roundtrip(parts: dict[str, bytes], document: ET.Element) -> tuple[dict[str, bytes], ET.Element]:
    with tempfile.TemporaryDirectory(prefix="rq4-docx-") as directory:
        path = Path(directory) / "mutated.docx"
        _write_docx(path, parts, document)
        reopened = _docx_parts(path)
        return reopened, _xml(reopened, "word/document.xml")


def _style_maps(styles: ET.Element) -> tuple[dict[str, ET.Element], dict[str, str]]:
    by_id: dict[str, ET.Element] = {}
    names: dict[str, str] = {}
    for style in styles.findall("./" + W + "style"):
        style_id = _val(style, "styleId") or ""
        by_id[style_id] = style
        names[style_id] = _norm(_val(style.find(W + "name")))
    return by_id, names


def _effective(style_id: str, styles: dict[str, ET.Element], path: str) -> ET.Element | None:
    seen = set()
    current = style_id
    while current and current not in seen:
        seen.add(current)
        style = styles.get(current)
        if style is None:
            return None
        found = style.find(path)
        if found is not None:
            return found
        current = _val(style.find(W + "basedOn")) or ""
    return None


def _t001(repo: Path) -> list[dict[str, Any]]:
    _parts, document, styles_root = _docx(repo)
    styles, names = _style_maps(styles_root)
    matches = [style_id for style_id, name in names.items() if name == "caption text" and _val(styles[style_id], "type") == "paragraph"]
    _assert(len(matches) == 1, "expected exactly one paragraph style named 'caption text'")
    style_id = matches[0]
    fonts = _effective(style_id, styles, "./" + W + "rPr/" + W + "rFonts")
    font_values = {_norm(fonts.get(W + key)) for key in ("ascii", "hAnsi", "eastAsia", "cs") if fonts is not None and fonts.get(W + key)}
    _assert(font_values == {"century gothic"}, f"caption text effective font is {sorted(font_values)}")
    italic = _effective(style_id, styles, "./" + W + "rPr/" + W + "i")
    _assert(italic is not None and _norm(_val(italic) or "true") not in {"0", "false", "off"}, "caption text is not effectively italic")
    size = _effective(style_id, styles, "./" + W + "rPr/" + W + "sz")
    _assert(_val(size) == "22", "caption text effective size is not 22 half-points")
    spacing = _effective(style_id, styles, "./" + W + "pPr/" + W + "spacing")
    _assert(_val(spacing, "line") == "300", "caption text effective line spacing is not 300 twips")
    classified = {"image": [], "table": []}
    for paragraph in document.findall(".//" + W + "p"):
        text = _norm(" ".join((n.text or "") for n in paragraph.findall(".//" + W + "t")))
        fields = _norm(" ".join((n.text or "") for n in paragraph.findall(".//" + W + "instrText")))
        bookmarks = _norm(" ".join((_val(n, "name") or "") for n in paragraph.findall(".//" + W + "bookmarkStart")))
        signature = " ".join((text, fields, bookmarks))
        p_style = _val(paragraph.find("./" + W + "pPr/" + W + "pStyle"))
        effective_name = names.get(p_style or "", "")
        is_heading = effective_name.startswith("heading")
        is_label = bool(re.search(r"\b(label|caption)\b", signature) or re.search(r"\bseq\s+(figure|table)\b", fields))
        if not is_heading and is_label and re.search(r"\b(image|figure|billede)\b", signature):
            classified["image"].append(effective_name)
        if not is_heading and is_label and re.search(r"\b(table|tabel)\b", signature):
            classified["table"].append(effective_name)
    for kind in ("image", "table"):
        _assert(classified[kind], f"no identifiable {kind}-label fixture paragraph exists")
        _assert(all(name == "caption text" for name in classified[kind]), f"{kind}-label fixture does not reference caption text")
    return [{"test_id": "T001-AC001-OBS001", "style_id": style_id}, {"test_id": "T001-AC002-OBS002", "status": "PASS"}]


def _t004(repo: Path) -> list[dict[str, Any]]:
    parts, document, _styles = _docx(repo)
    controls = _interactive(document)
    _assert(bool(controls), "DOCX has no interactive content controls")
    tags = [_tag(control) for control in controls]
    _assert(all(tags), "an interactive control has an empty tag")
    _assert(len(tags) == len(set(tags)), "interactive control tags are not unique")
    aliases = _mapping(controls, _alias)
    initial = _mapping(controls, _direct_text)
    _assert(all(aliases[tag] and aliases[tag] == initial[tag] for tag in tags), "a control alias does not match its initial visible instruction")
    for index, control in enumerate(controls, 1):
        _replace_content(control, [f"Fixture user text {index}"])
    _changed_parts, reopened = _roundtrip(parts, document)
    reopened_controls = _interactive(reopened)
    _assert(_mapping(reopened_controls, _alias) == aliases, "tag-to-alias mapping changed after content replacement")
    _assert(all(_direct_text(control) != _alias(control) for control in reopened_controls), "replacement content equals retained alias")
    return [{"test_id": "T004-AC001-OBS001", "control_count": len(tags)}, {"test_id": "T004-AC002-OBS002", "status": "PASS"}]


def _t005(repo: Path) -> list[dict[str, Any]]:
    parts, document, _styles = _docx(repo)
    controls = _interactive(document)
    glossary = _glossary(parts)
    _assert(bool(controls), "DOCX has no interactive content controls")
    for control in controls:
        alias = _alias(control)
        instruction = _instruction(control, glossary)
        _assert(bool(alias), "interactive control has an empty label")
        _assert(bool(instruction), "interactive control has empty initial/placeholder text")
        _assert(alias == instruction, "interactive control label differs from initial instruction")
    return [{"test_id": "T005-AC001-OBS001", "control_count": len(controls)}]


def _t006(repo: Path) -> list[dict[str, Any]]:
    parts, document, _styles = _docx(repo)
    controls = _interactive(document)
    glossary = _glossary(parts)
    _assert(bool(controls), "DOCX has no interactive content controls")
    tags = [_tag(control) for control in controls]
    _assert(all(tags) and len(tags) == len(set(tags)), "interactive control tags must be non-empty and unique")
    aliases = _mapping(controls, _alias)
    placeholders = _mapping(controls, lambda control: glossary.get(_placeholder_name(control), ""))
    _assert(all(aliases.values()), "interactive control has blank alias/help metadata")
    _assert(all(_placeholder_name(control) and placeholders[_tag(control)] for control in controls), "interactive control has missing or dangling placeholder")
    for control in controls:
        _replace_content(control, [""])
    changed_parts, reopened = _roundtrip(parts, document)
    reopened_controls = _interactive(reopened)
    changed_glossary = _glossary(changed_parts)
    _assert(_mapping(reopened_controls, _alias) == aliases, "tag-to-alias mapping changed after clearing")
    after_placeholders = _mapping(reopened_controls, lambda control: changed_glossary.get(_placeholder_name(control), ""))
    _assert(after_placeholders == placeholders, "tag-to-resolved-placeholder mapping changed after clearing")
    return [{"test_id": "T006-AC001-OBS001", "control_count": len(controls)}]


def _t007(repo: Path) -> list[dict[str, Any]]:
    parts, document, _styles = _docx(repo)
    controls = _interactive(document)
    glossary = _glossary(parts)
    _assert(bool(controls), "DOCX has no interactive content controls")
    dangling = 0
    matching = 0
    for control in controls:
        reference = _placeholder_name(control)
        resolved = glossary.get(reference, "") if reference else ""
        if reference and not resolved:
            dangling += 1
        instruction = _direct_text(control) or resolved
        _assert(bool(instruction), "interactive control has blank direct and resolved instruction")
        if _alias(control) and _alias(control) == instruction:
            matching += 1
    _assert(dangling == 0, "interactive control has dangling placeholder reference")
    _assert(matching >= 1, "no control duplicates matching help text in label and field")
    return [{"test_id": "T007-AC001-OBS001", "control_count": len(controls)}, {"test_id": "T007-AC002-OBS002", "matching_controls": matching}]


def _t011(repo: Path) -> list[dict[str, Any]]:
    parts, document, _styles = _docx(repo)
    candidates = []
    for control in _interactive(document):
        signature = " ".join((_tag(control), _alias(control), _direct_text(control)))
        if re.search(r"\bheadline\b", signature):
            candidates.append(control)
    _assert(len(candidates) == 1, "expected exactly one headline-tagged interactive content control")
    control = candidates[0]
    properties = control.find(W + "sdtPr")
    text_property = properties.find(W + "text") if properties is not None else None
    _assert(_norm(_val(text_property, "multiLine")) in {"1", "true", "on"}, "headline text control is not configured for multiline input")
    tag = _tag(control)
    _replace_content(control, ["First fixture line", "Second fixture line"])
    _changed, reopened = _roundtrip(parts, document)
    matches = [item for item in _interactive(reopened) if _tag(item) == tag]
    _assert(len(matches) == 1, "headline control split or disappeared after multiline save")
    content = matches[0].find(W + "sdtContent")
    paragraphs = content.findall("./" + W + "p") if content is not None else []
    _assert(len(paragraphs) == 2, "headline control did not retain two ordinary paragraphs")
    _assert(not matches[0].findall(".//" + W + "br"), "multiline fixture was stored using manual line breaks")
    return [{"test_id": "T011-AC001-OBS001", "paragraph_count": len(paragraphs)}]


TARGETS: dict[str, Callable[[Path], list[dict[str, Any]]]] = {
    "43255761_T001": _t001,
    "43255761_T004": _t004,
    "43255761_T005": _t005,
    "43255761_T006": _t006,
    "43255761_T007": _t007,
    "43255761_T011": _t011,
}


def _write_result(path: Path, result: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(target_id: str) -> int:
    parser = argparse.ArgumentParser(description="Hidden deterministic DOCX/OOXML RQ4 validator")
    parser.add_argument("--component", required=True, choices=("build", "target", "regression"))
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    result = {"schema_version": SCHEMA_VERSION, "target_id": target_id, "component": args.component, "status": "HARNESS_FAULT", "checks": [], "failures": []}
    exit_code = 2
    try:
        repo = _repo(args.repo)
        if args.component == "build":
            result["checks"] = _build(repo)
        elif args.component == "regression":
            result["checks"] = _regression(repo)
        else:
            result["checks"] = TARGETS[target_id](repo)
        result["status"] = "PASS"
        exit_code = 0
    except CandidateFailure as exc:
        result["status"] = "CANDIDATE_FAIL"
        result["failures"] = [str(exc)]
        exit_code = 1
    except HarnessFault as exc:
        result["status"] = "HARNESS_FAULT"
        result["failures"] = [str(exc)]
        exit_code = 2
    except Exception as exc:
        result["status"] = "HARNESS_FAULT"
        result["failures"] = [f"unexpected validator error: {type(exc).__name__}: {exc}"]
        exit_code = 2
    try:
        _write_result(args.result, result)
    except OSError as exc:
        result["status"] = "HARNESS_FAULT"
        result["failures"] = [f"cannot write result: {exc}"]
        exit_code = 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code
