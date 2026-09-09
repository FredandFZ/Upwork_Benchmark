import feature001 from "./features/bullet-visual-formatting.mjs";
import feature002 from "./features/column-overflow-containment.mjs";
import feature003 from "./features/consistent-new-style-system.mjs";
import feature004 from "./features/danish-template-language-configuration.mjs";
import feature005 from "./features/legacy-content-copy-paste-stability.mjs";
import feature006 from "./features/line-break-entry-after-legacy-paste.mjs";
import feature007 from "./features/modern-word-for-windows-compatibility.mjs";
import feature008 from "./features/numbered-list-alignment.mjs";
import feature009 from "./features/pbu-style-naming.mjs";
import feature010 from "./features/tab-driven-list-hierarchy.mjs";
import feature011 from "./features/table-paste-layout-stability.mjs";
import { buildProfile } from "./profile.mjs";

const features = Object.freeze([feature001, feature002, feature003, feature004, feature005, feature006, feature007, feature008, feature009, feature010, feature011]);
const stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));

export const profile = buildProfile(features);
export const snapshot = Object.freeze({
  environment: "reconstructed-pre-event",
  documentLabel: "Reconstructed Word template",
  features,
  stateMap,
});
