import feature001 from "./features/confidential-distribution-warning.mjs";
import feature002 from "./features/consistent-page-footer.mjs";
import feature003 from "./features/design-asset-handoff.mjs";
import feature004 from "./features/editable-customer-specific-fields.mjs";
import feature005 from "./features/footer-code-consistency.mjs";
import feature006 from "./features/front-page-result-dashboard.mjs";
import feature007 from "./features/internal-header-code-consistency.mjs";
import feature008 from "./features/internal-page-header.mjs";
import feature009 from "./features/premium-report-visual-design.mjs";
import feature010 from "./features/prioritized-security-upgrade-path.mjs";
import feature011 from "./features/report-detail-code-consistency.mjs";
import feature012 from "./features/rr01-rr04-report-variant-set.mjs";
import feature013 from "./features/scannable-result-explanation.mjs";
import feature014 from "./features/scoring-summary-table.mjs";
import feature015 from "./features/vehicle-group-presentation.mjs";
import { buildProfile } from "./profile.mjs";

const features = Object.freeze([feature001, feature002, feature003, feature004, feature005, feature006, feature007, feature008, feature009, feature010, feature011, feature012, feature013, feature014, feature015]);
const stateMap = Object.freeze(Object.fromEntries(features.map((feature) => [feature.requirement_id, feature.state_id])));

export const profile = buildProfile(features);
export const snapshot = Object.freeze({
  environment: "reconstructed-pre-event",
  documentLabel: "Reconstructed report template",
  features,
  stateMap,
});
