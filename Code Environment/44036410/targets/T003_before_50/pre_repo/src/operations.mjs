export function dashboard(profile) {
  return Object.freeze({ heading: profile.scoreHeading, value: profile.scoreValue, risk: profile.riskLabel, fontSize: profile.scoreFontSize, failed: profile.dashboardFailed });
}

export function explanation(profile) {
  return Object.freeze({ items: [...profile.explanationItems], dense: profile.explanationDense, scannable: !profile.explanationDense && profile.explanationItems.length <= 4 });
}

export function vehiclePresentation(profile) {
  return Object.freeze({ mode: profile.vehicleUsesCheckboxes ? "checkbox-form" : "customer-report-line", completedReportAppearance: !profile.vehicleUsesCheckboxes });
}

export function distributionWarning(profile) {
  return Object.freeze({ enabled: profile.warningEnabled, text: profile.warningText, prominence: profile.warningStyle, subordinate: profile.warningStyle === "subtle" });
}

export function footerForPage(profile, pageNumber) {
  const present = pageNumber >= 1 && pageNumber <= 4 && (profile.footerAllPages || pageNumber < 4);
  return Object.freeze({ pageNumber, present, code: present ? profile.footerCode : null });
}

export function reportCodeLocations(profile) {
  return Object.freeze({ body: profile.bodyCode, internalHeader: profile.headerCode, footer: profile.footerCode, consistent: new Set([profile.bodyCode, profile.headerCode, profile.footerCode]).size === 1 });
}
