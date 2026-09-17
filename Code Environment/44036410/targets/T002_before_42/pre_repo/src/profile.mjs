const DEFAULT_PROFILE = Object.freeze({
  documentLanguage: "en-US",
  titleHalfPoints: 48,
  bulletGlyph: "-",
  bulletApproved: false,
  accentHex: "17365D",
  stylePrefix: "",
  formRows: Object.freeze(["Field A", "Field B", "Field C", "Field D"]),
  firstRowIndentDxa: 0,
  premium: false,
  scoreHeading: "Score",
  scoreValue: "62 / 100",
  scoreFontSize: 34,
  reportTitle: "Evaluation Report",
  reportCodeLabel: "Reference",
  dateLabel: "Record date",
  riskHeading: "Category",
  dashboardReasonHeading: "Result explanation",
  detailsHeading: "Evaluation details",
  subjectLabel: "Subject group",
  subjectValue: "Evaluated subject",
  contextHeading: "Context",
  priorityHeading: "Priority actions",
  riskLabel: "Moderate",
  dashboardFailed: false,
  explanationDense: false,
  explanationItems: Object.freeze(["Primary result reason", "Main exposure", "Priority action"]),
  vehicleUsesCheckboxes: false,
  warningEnabled: false,
  warningText: "Restricted distribution",
  warningStyle: "subtle",
  assessmentDate: "[Record date]",
  headerEnabled: false,
  footerAllPages: true,
  bodyCode: "RP-00",
  headerCode: "RP-00",
  footerCode: "RP-00",
  copyLines: Object.freeze(["Evaluation detail remains concise.", "Recommendations match the observed category."]),
});

function cleanHex(value) {
  return typeof value === "string" && /^[0-9A-F]{6}$/i.test(value) ? value.toUpperCase() : DEFAULT_PROFILE.accentHex;
}

export function buildProfile(features) {
  const merged = { ...DEFAULT_PROFILE, formRows: [...DEFAULT_PROFILE.formRows], explanationItems: [...DEFAULT_PROFILE.explanationItems], copyLines: [...DEFAULT_PROFILE.copyLines] };
  for (const feature of features) {
    const hints = feature.render_hints ?? {};
    for (const key of ["documentLanguage", "bulletGlyph", "stylePrefix", "scoreHeading", "scoreValue", "riskLabel", "reportTitle", "reportCodeLabel", "dateLabel", "riskHeading", "dashboardReasonHeading", "detailsHeading", "subjectLabel", "subjectValue", "contextHeading", "priorityHeading", "warningText", "warningStyle", "assessmentDate", "bodyCode", "headerCode", "footerCode"]) {
      if (typeof hints[key] === "string") merged[key] = hints[key].slice(0, 240);
    }
    for (const key of ["bulletApproved", "premium", "dashboardFailed", "explanationDense", "vehicleUsesCheckboxes", "warningEnabled", "headerEnabled", "footerAllPages"]) {
      if (typeof hints[key] === "boolean") merged[key] = hints[key];
    }
    if (Number.isInteger(hints.titleHalfPoints) && hints.titleHalfPoints >= 20 && hints.titleHalfPoints <= 144) merged.titleHalfPoints = hints.titleHalfPoints;
    if (Number.isInteger(hints.scoreFontSize) && hints.scoreFontSize >= 20 && hints.scoreFontSize <= 72) merged.scoreFontSize = hints.scoreFontSize;
    if (typeof hints.accentHex === "string") merged.accentHex = cleanHex(hints.accentHex);
    if (Array.isArray(hints.formRows) && hints.formRows.length === 4 && hints.formRows.every((item) => typeof item === "string")) merged.formRows = [...hints.formRows];
    if (Array.isArray(hints.explanationItems) && hints.explanationItems.length > 0) merged.explanationItems = hints.explanationItems.map(String).slice(0, 8);
    if (Array.isArray(hints.copyLines) && hints.copyLines.length > 0) merged.copyLines = hints.copyLines.map(String).slice(0, 4);
  }
  const diagnostics = features.filter((feature) => feature.execution).map((feature) => ({ requirement_id: feature.requirement_id, ...feature.execution }));
  const openQuestions = features.flatMap((feature) => Object.values(feature.ambiguity ?? {}).map((item) => ({ requirement_id: feature.requirement_id, ...item })));
  return Object.freeze({ ...merged, activeRequirementCount: features.length, diagnostics, openQuestions });
}
