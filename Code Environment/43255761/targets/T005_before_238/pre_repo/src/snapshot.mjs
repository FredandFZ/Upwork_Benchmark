import feature001 from "./features/bullet-visual-formatting.mjs";
import feature002 from "./features/checklist-control.mjs";
import feature003 from "./features/column-overflow-containment.mjs";
import feature004 from "./features/consistent-new-style-system.mjs";
import feature005 from "./features/controlled-theme-color-palette.mjs";
import feature006 from "./features/customer-designed-powerpoint-template.mjs";
import feature007 from "./features/danish-template-language-configuration.mjs";
import feature008 from "./features/dropdown-control.mjs";
import feature009 from "./features/interactive-field-formatting-stability.mjs";
import feature010 from "./features/interactive-field-help-labels.mjs";
import feature011 from "./features/legacy-content-copy-paste-stability.mjs";
import feature012 from "./features/line-break-entry-after-legacy-paste.mjs";
import feature013 from "./features/list-continuation-on-enter.mjs";
import feature014 from "./features/modern-word-for-windows-compatibility.mjs";
import feature015 from "./features/numbered-list-alignment.mjs";
import feature016 from "./features/page-fit-spacing.mjs";
import feature017 from "./features/page-numbering-from-page-two.mjs";
import feature018 from "./features/pbu-style-naming.mjs";
import feature019 from "./features/placeholder-clear-on-activation.mjs";
import feature020 from "./features/reusable-date-selector.mjs";
import feature021 from "./features/robust-standard-text-placeholders.mjs";
import feature022 from "./features/shared-master-template-foundation.mjs";
import feature023 from "./features/tab-driven-list-hierarchy.mjs";
import feature024 from "./features/table-paste-layout-stability.mjs";
import feature025 from "./features/template-style-typography.mjs";
import feature026 from "./features/versioned-complete-template-package.mjs";
import feature027 from "./features/visible-fillable-field-cues.mjs";
import { buildProfile } from "./profile.mjs";

const features = Object.freeze([feature001, feature002, feature003, feature004, feature005, feature006, feature007, feature008, feature009, feature010, feature011, feature012, feature013, feature014, feature015, feature016, feature017, feature018, feature019, feature020, feature021, feature022, feature023, feature024, feature025, feature026, feature027]);
const stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));

export const profile = buildProfile(features);
export const snapshot = Object.freeze({
  environment: "reconstructed-pre-event",
  documentLabel: "Reconstructed Word template",
  features,
  stateMap,
});
