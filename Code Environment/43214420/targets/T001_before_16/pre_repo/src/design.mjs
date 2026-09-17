import fs from "node:fs";
import path from "node:path";
import { quoteSExpression } from "./sexpr.mjs";

function boardText(profile, snapshot) {
  const width = profile.boardWidthMm;
  const height = profile.boardHeightMm;
  const annotations = [
    profile.projectTitle,
    `${snapshot.features.length} graph-backed requirement states`,
    `variant ${profile.boardVariant}`,
  ];
  const graphicText = annotations.map((item, index) => `  (gr_text ${quoteSExpression(item)} (at 10 ${10 + index * 3}) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))`).join("\n");
  return `(kicad_pcb (version 20240108) (generator rq4_reconstruction)\n  (general (thickness 1.6))\n  (paper "A4")\n  (layers\n    (0 "F.Cu" signal)\n    (31 "B.Cu" signal)\n    (36 "B.SilkS" user "b.silkscreen")\n    (37 "F.SilkS" user "f.silkscreen")\n    (44 "Edge.Cuts" user)\n  )\n${graphicText}\n  (gr_rect (start 0 0) (end ${width} ${height}) (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts"))\n)\n`;
}

function schematicText(profile, snapshot) {
  const description = `${profile.projectTitle}; ${snapshot.features.length} active requirement states`;
  return `(kicad_sch (version 20231120) (generator rq4_reconstruction)\n  (uuid 00000000-0000-4000-8000-000000000001)\n  (paper "A4")\n  (lib_symbols)\n  (text ${quoteSExpression(description)} (exclude_from_sim no) (at 25.4 25.4 0) (effects (font (size 1.27 1.27))))\n  (sheet_instances (path "/" (page "1")))\n)\n`;
}

export function writeDesignArtifacts(outputRoot, profile, snapshot) {
  fs.mkdirSync(outputRoot, { recursive: true });
  fs.writeFileSync(path.join(outputRoot, "design.kicad_pcb"), boardText(profile, snapshot), "utf8");
  fs.writeFileSync(path.join(outputRoot, "design.kicad_sch"), schematicText(profile, snapshot), "utf8");
  fs.writeFileSync(path.join(outputRoot, "design-state.json"), `${JSON.stringify({ environment: snapshot.environment, state_map: snapshot.stateMap, profile }, null, 2)}\n`, "utf8");
}
