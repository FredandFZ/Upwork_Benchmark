import feature001 from "./features/battery-safety-protection.mjs";
import feature002 from "./features/pcb-architecture-variants.mjs";
import { buildProfile } from "./profile.mjs";

const features = Object.freeze([feature001, feature002]);
const stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));

export const profile = buildProfile(features);
export const snapshot = Object.freeze({ environment: "reconstructed-pre-event", features, stateMap });
