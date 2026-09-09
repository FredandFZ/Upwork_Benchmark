import feature001 from "./features/bullet-visual-formatting.mjs";
import feature002 from "./features/column-overflow-containment.mjs";
import feature003 from "./features/consistent-new-style-system.mjs";
import feature004 from "./features/controlled-theme-color-palette.mjs";
import feature005 from "./features/danish-template-language-configuration.mjs";
import feature006 from "./features/interactive-field-formatting-stability.mjs";
import feature007 from "./features/legacy-content-copy-paste-stability.mjs";
import feature008 from "./features/line-break-entry-after-legacy-paste.mjs";
import feature009 from "./features/list-continuation-on-enter.mjs";
import feature010 from "./features/modern-word-for-windows-compatibility.mjs";
import feature011 from "./features/numbered-list-alignment.mjs";
import feature012 from "./features/page-fit-spacing.mjs";
import feature013 from "./features/page-numbering-from-page-two.mjs";
import feature014 from "./features/pbu-style-naming.mjs";
import feature015 from "./features/placeholder-clear-on-activation.mjs";
import feature016 from "./features/robust-standard-text-placeholders.mjs";
import feature017 from "./features/shared-master-template-foundation.mjs";
import feature018 from "./features/tab-driven-list-hierarchy.mjs";
import feature019 from "./features/table-paste-layout-stability.mjs";
import feature020 from "./features/template-style-typography.mjs";
import feature021 from "./features/visible-fillable-field-cues.mjs";
import { buildProfile } from "./profile.mjs";

const features = Object.freeze([feature001, feature002, feature003, feature004, feature005, feature006, feature007, feature008, feature009, feature010, feature011, feature012, feature013, feature014, feature015, feature016, feature017, feature018, feature019, feature020, feature021]);
const stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));

export const profile = buildProfile(features);
export const snapshot = Object.freeze({
  environment: "reconstructed-pre-event",
  documentLabel: "Reconstructed Word template",
  features,
  stateMap,
});
