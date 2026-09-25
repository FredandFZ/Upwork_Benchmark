from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re


def _quoted(value):
    return str(value).replace("\\", "\\\\").replace('"', "'")


def _value(value):
    if isinstance(value, (dict, list, bool, int, float)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _all_nets(model):
    ordered = []
    members = {}
    for item in model.get("nets", []):
        name = item["name"]
        if name not in ordered:
            ordered.append(name)
        members.setdefault(name, []).extend(item.get("members", []))
    for component in model.get("components", []):
        for pin in component.get("pins", []):
            name = pin["net"]
            if name not in ordered:
                ordered.append(name)
            member = f'{component["reference"]}.{pin["number"]}'
            if member not in members.setdefault(name, []):
                members[name].append(member)
    return [{"name": name, "members": members.get(name, [])} for name in ordered]


def _component_footprint(component, net_ids):
    reference = component["reference"]
    library_id = component["footprint"]
    x, y = component["at_mm"]
    rotation = component.get("rotation_deg", 0)
    side = component.get("side", "F.Cu")
    courtyard_layer = "B.CrtYd" if side == "B.Cu" else "F.CrtYd"
    width, height = component.get("courtyard_mm", [6.0, 6.0])
    lines = [
        f'  (footprint "{_quoted(library_id)}" (layer "{side}") (at {x} {y} {rotation})',
        f'    (property "Reference" "{_quoted(reference)}" (at 0 {-height / 2 - 1} 0) (layer "{courtyard_layer}"))',
        f'    (property "Value" "{_quoted(component["value"])}" (at 0 {height / 2 + 1} 0) (layer "{courtyard_layer}"))',
        f'    (fp_rect (start {-width / 2} {-height / 2}) (end {width / 2} {height / 2}) (stroke (width 0.05) (type default)) (fill none) (layer "{courtyard_layer}"))',
    ]
    pins = component.get("pins", [])
    pitch = float(component.get("pin_pitch_mm", 2.54))
    mounting = component.get("mounting_style", "tht").lower()
    for index, pin in enumerate(pins):
        offset = (index - (len(pins) - 1) / 2) * pitch
        number = _quoted(pin["number"])
        net = _quoted(pin["net"])
        if mounting == "smd":
            layers = '"B.Cu" "B.Paste" "B.Mask"' if side == "B.Cu" else '"F.Cu" "F.Paste" "F.Mask"'
            lines.append(f'    (pad "{number}" smd roundrect (at {offset} 0) (size 1.4 2.2) (layers {layers}) (roundrect_rratio 0.2) (net {net_ids[pin["net"]]} "{net}"))')
        else:
            lines.append(f'    (pad "{number}" thru_hole circle (at {offset} 0) (size 1.8 1.8) (drill 0.9) (layers "*.Cu" "*.Mask") (net {net_ids[pin["net"]]} "{net}"))')
    lines.append("  )")
    return "\n".join(lines)


def build_kicad_files(model, output):
    output = Path(output)
    nets = _all_nets(model)
    net_ids = {item["name"]: index + 1 for index, item in enumerate(nets)}
    symbols = []
    for component in model.get("components", []):
        x, y = component["at_mm"]
        properties = [
            ("Reference", component["reference"]),
            ("Value", component["value"]),
            ("Footprint", component["footprint"]),
            ("BoardSide", component.get("side", "F.Cu")),
            ("MountingStyle", component.get("mounting_style", "tht")),
        ]
        properties.extend((f'Pin{pin["number"]}', f'{pin.get("name", pin["number"])}|{pin["net"]}') for pin in component.get("pins", []))
        properties.extend((f"Meta.{key}", _value(value)) for key, value in sorted(component.get("properties", {}).items()))
        prop_text = " ".join(f'(property "{_quoted(key)}" "{_quoted(value)}")' for key, value in properties)
        symbols.append(f'  (symbol (lib_id "Generated:{_quoted(component["value"])}") (at {x} {y} {component.get("rotation_deg", 0)}) {prop_text})')
    schematic = "(kicad_sch (version 20231120) (generator rq4_reference)\n  (uuid 00000000-0000-0000-0000-000000000001)\n  (paper \"A4\")\n" + "\n".join(symbols) + "\n  (sheet_instances (path \"/\" (page \"1\")))\n)\n"

    footprint_text = [_component_footprint(component, net_ids) for component in model.get("components", [])]
    for hole in model.get("geometry", {}).get("holes", []):
        x, y = hole["at_mm"]
        diameter = float(hole.get("diameter_mm", 2.7))
        footprint_text.append(
            f'  (footprint "MountingHole:MountingHole_{diameter:.1f}mm" (layer "F.Cu") (at {x} {y}) '
            f'(property "Reference" "{_quoted(hole["reference"])}" (at 0 -3 0) (layer "F.SilkS")) '
            f'(property "Value" "{_quoted(hole.get("fastener", "M2.5"))} mounting hole" (at 0 3 0) (layer "F.Fab")) '
            f'(fp_circle (center 0 0) (end {diameter / 2 + 1} 0) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd")) '
            f'(pad "" np_thru_hole circle (at 0 0) (size {diameter} {diameter}) (drill {diameter}) (layers "*.Cu" "*.Mask")))'
        )
    points = model["geometry"]["outline"]
    outline = [f'  (gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (stroke (width 0.05) (type default)) (layer "Edge.Cuts"))' for a, b in zip(points, points[1:])]
    markings = [f'  (gr_text "{_quoted(text)}" (at 5 {5 + index * 2}) (layer "F.SilkS"))' for index, text in enumerate(model.get("geometry", {}).get("markings", []))]
    net_text = [f'  (net {index + 1} "{_quoted(item["name"])}")' for index, item in enumerate(nets)]
    pcb = "(kicad_pcb (version 20240108) (generator rq4_reference)\n  (general (thickness 1.6))\n  (layers (0 \"F.Cu\" signal) (31 \"B.Cu\" signal) (36 \"B.SilkS\" user \"b.silkscreen\") (37 \"F.SilkS\" user \"f.silkscreen\") (44 \"Edge.Cuts\" user) (46 \"B.CrtYd\" user \"b.courtyard\") (47 \"F.CrtYd\" user \"f.courtyard\"))\n" + "\n".join(net_text + footprint_text + outline + markings) + "\n)\n"
    (output / "design.kicad_sch").write_text(schematic, encoding="utf-8")
    (output / "design.kicad_pcb").write_text(pcb, encoding="utf-8")
    return nets


def _blocks(text, name):
    result = []
    start_pattern = re.compile(rf"\({re.escape(name)}(?:\s|\")")
    for match in start_pattern.finditer(text):
        start = match.start()
        depth = 0
        quoted = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if escaped:
                escaped = False
            elif quoted and char == "\\":
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted and char == "(":
                depth += 1
            elif not quoted and char == ")":
                depth -= 1
                if depth == 0:
                    result.append(text[start:index + 1])
                    break
    return result


def _balanced(text):
    depth = 0
    quoted = False
    escaped = False
    for char in text:
        if escaped:
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quoted


def parse_kicad_files(output):
    output = Path(output)
    schematic_text = (output / "design.kicad_sch").read_text(encoding="utf-8")
    pcb_text = (output / "design.kicad_pcb").read_text(encoding="utf-8")
    components = []
    for block in _blocks(schematic_text, "symbol"):
        properties = dict(re.findall(r'\(property\s+"([^"]+)"\s+"([^"]*)"', block))
        pins = []
        for key, value in properties.items():
            if key.startswith("Pin"):
                name, net = value.split("|", 1)
                pins.append({"number": key[3:], "name": name, "net": net})
        metadata = {}
        for key, value in properties.items():
            if key.startswith("Meta."):
                try:
                    metadata[key[5:]] = json.loads(value)
                except json.JSONDecodeError:
                    metadata[key[5:]] = value
        components.append({"reference": properties.get("Reference"), "value": properties.get("Value"),
                           "footprint": properties.get("Footprint"), "side": properties.get("BoardSide"),
                           "mounting_style": properties.get("MountingStyle"), "pins": pins,
                           "properties": metadata})

    footprints = []
    holes = []
    net_members = {}
    for block in _blocks(pcb_text, "footprint"):
        library = re.search(r'^\(footprint\s+"([^"]+)"', block)
        reference = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        layer = re.search(r'\(layer\s+"([^"]+)"\)', block)
        at = re.search(r'\(at\s+([\d.-]+)\s+([\d.-]+)(?:\s+([\d.-]+))?\)', block)
        pads = []
        for pad_block in _blocks(block, "pad"):
            header = re.search(r'^\(pad\s+"([^"]*)"\s+(\S+)', pad_block)
            local_at = re.search(r'\(at\s+([\d.-]+)\s+([\d.-]+)', pad_block)
            net = re.search(r'\(net\s+\d+\s+"([^"]+)"\)', pad_block)
            drill = re.search(r'\(drill\s+([\d.-]+)\)', pad_block)
            pad = {"number": header.group(1) if header else "", "type": header.group(2) if header else None,
                   "at_mm": [float(local_at.group(1)), float(local_at.group(2))] if local_at else [0.0, 0.0],
                   "net": net.group(1) if net else None, "drill_mm": float(drill.group(1)) if drill else None}
            pads.append(pad)
            if pad["net"] and reference:
                net_members.setdefault(pad["net"], []).append(f'{reference.group(1)}.{pad["number"]}')
        courtyard = re.search(r'\(fp_rect\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s+\(end\s+([\d.-]+)\s+([\d.-]+)\)', block)
        record = {"library_id": library.group(1) if library else None,
                  "reference": reference.group(1) if reference else None,
                  "side": layer.group(1) if layer else None,
                  "at_mm": [float(at.group(1)), float(at.group(2))] if at else None,
                  "rotation_deg": float(at.group(3) or 0) if at else 0,
                  "pads": pads,
                  "courtyard_mm": [abs(float(courtyard.group(3)) - float(courtyard.group(1))), abs(float(courtyard.group(4)) - float(courtyard.group(2)))] if courtyard else None}
        footprints.append(record)
        if record["library_id"] and record["library_id"].startswith("MountingHole:"):
            hole_pad = pads[0] if pads else {}
            value = re.search(r'\(property\s+"Value"\s+"([^"]+)"', block)
            holes.append({"reference": record["reference"], "at_mm": record["at_mm"],
                          "diameter_mm": hole_pad.get("drill_mm"), "fastener": (value.group(1).split()[0] if value else None)})
    nets = [{"id": int(number), "name": name, "members": net_members.get(name, [])}
            for number, name in re.findall(r'^\s*\(net\s+(\d+)\s+"([^"]+)"\)', pcb_text, re.MULTILINE)]
    lines = [[float(a), float(b), float(c), float(d)] for a, b, c, d in re.findall(r'\(gr_line\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s+\(end\s+([\d.-]+)\s+([\d.-]+)\).*?\(layer\s+"Edge.Cuts"\)', pcb_text)]
    points = [[line[0], line[1]] for line in lines]
    if lines:
        points.append([lines[-1][2], lines[-1][3]])
    xs = [point[0] for point in points] or [0.0]
    ys = [point[1] for point in points] or [0.0]
    markings = re.findall(r'\(gr_text\s+"([^"]+)"', pcb_text)
    return {"components": components, "footprints": footprints, "nets": nets,
            "geometry": {"outline": points, "board_size": {"width": max(xs) - min(xs), "height": max(ys) - min(ys)},
                         "holes": holes, "markings": markings},
            "balanced": _balanced(schematic_text) and _balanced(pcb_text)}


def validate_kicad_model(model, parsed):
    if not parsed["balanced"]:
        raise RuntimeError("generated KiCad syntax is unbalanced")
    expected_components = {item["reference"]: item for item in model.get("components", [])}
    actual_components = {item["reference"]: item for item in parsed["components"]}
    if set(expected_components) != set(actual_components):
        raise RuntimeError("schematic component references do not match the model")
    footprints = {item["reference"]: item for item in parsed["footprints"]}
    if not set(expected_components).issubset(footprints):
        raise RuntimeError("PCB footprints do not cover every schematic component")
    member_sets = {item["name"]: set(item["members"]) for item in parsed["nets"]}
    for component in model.get("components", []):
        for pin in component.get("pins", []):
            member = f'{component["reference"]}.{pin["number"]}'
            if member not in member_sets.get(pin["net"], set()):
                raise RuntimeError(f"missing pad-to-net mapping for {member}")
    expected_holes = model.get("geometry", {}).get("holes", [])
    if len(parsed["geometry"]["holes"]) != len(expected_holes):
        raise RuntimeError("mounting-hole count does not match the model")
    outline = parsed["geometry"]["outline"]
    if len(outline) < 4 or outline[0] != outline[-1]:
        raise RuntimeError("Edge.Cuts outline is not closed")
    return True
