import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { breakoutStatus, connectorLayout, inputInterfaces, manufacturingStatus, mechanicalEnvelope, powerSafety } from "../src/operations.mjs";
import { assertBalancedSExpression } from "../src/sexpr.mjs";
import { profile, snapshot } from "../src/snapshot.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("snapshot maps every projected requirement exactly once", () => {
  assert.equal(snapshot.features.length, Object.keys(snapshot.stateMap).length);
  assert.equal(new Set(snapshot.features.map((item) => item.requirement_id)).size, snapshot.features.length);
  for (const feature of snapshot.features) assert.equal(snapshot.stateMap[feature.requirement_id], feature.state_id);
  assert.equal(profile.activeRequirementCount, snapshot.features.length);
});

test("behavior operations expose the projected electrical and mechanical state", () => {
  assert.equal(mechanicalEnvelope(profile).mounting_holes, profile.mountingHoleCount);
  assert.equal(connectorLayout(profile).top_edge_aligned, profile.connectorTopAligned);
  assert.equal(breakoutStatus(profile).full_pin_breakout, profile.fullPinBreakout);
  assert.equal(powerSafety(profile).vbackup_access, profile.vbackupAccess);
  assert.equal(inputInterfaces(profile).touch_inputs, profile.touchInputCount);
  assert.equal(manufacturingStatus(profile).bom_status, profile.bomStatus);
});

test("generated KiCad fixtures have recognized roots and balanced syntax", () => {
  const pcb = fs.readFileSync(path.join(root, "artifacts", "design.kicad_pcb"), "utf8");
  const sch = fs.readFileSync(path.join(root, "artifacts", "design.kicad_sch"), "utf8");
  assert.ok(pcb.startsWith("(kicad_pcb "));
  assert.ok(sch.startsWith("(kicad_sch "));
  assertBalancedSExpression(pcb, "PCB");
  assertBalancedSExpression(sch, "schematic");
  assert.match(pcb, /\(layer "Edge\.Cuts"\)/);
});

test("design-state artifact equals the in-memory temporal snapshot", () => {
  const state = JSON.parse(fs.readFileSync(path.join(root, "artifacts", "design-state.json"), "utf8"));
  assert.deepEqual(state.state_map, snapshot.stateMap);
  assert.equal(state.profile.activeRequirementCount, snapshot.features.length);
});
