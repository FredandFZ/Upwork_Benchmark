import feature001 from "./features/consistent-page-footer.mjs";
import feature002 from "./features/design-asset-handoff.mjs";
import feature003 from "./features/editable-customer-specific-fields.mjs";
import feature004 from "./features/front-page-result-dashboard.mjs";
import feature005 from "./features/internal-page-header.mjs";
import feature006 from "./features/premium-report-visual-design.mjs";
import feature007 from "./features/prioritized-security-upgrade-path.mjs";
import feature008 from "./features/rr01-rr04-report-variant-set.mjs";
import feature009 from "./features/scannable-result-explanation.mjs";
import feature010 from "./features/scoring-summary-table.mjs";
import { buildProfile } from "./profile.mjs";

const features = Object.freeze([feature001, feature002, feature003, feature004, feature005, feature006, feature007, feature008, feature009, feature010]);
const stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));

export const profile = buildProfile(features);
export const snapshot = Object.freeze({
  environment: "reconstructed-pre-event",
  documentLabel: "Reconstructed report template",
  features,
  stateMap,
});
