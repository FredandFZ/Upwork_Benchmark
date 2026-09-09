import { buildProfile } from "./profile.mjs";

const features = Object.freeze([]);
const stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));

export const profile = buildProfile(features);
export const snapshot = Object.freeze({
  environment: "completed-zero-domain-baseline",
  documentLabel: "Executable Word template",
  features,
  stateMap,
});
