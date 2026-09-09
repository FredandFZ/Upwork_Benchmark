const DEFAULT_PROFILE = Object.freeze({
  documentLanguage: "en-US",
  titleHalfPoints: 48,
  bulletGlyph: "•",
  bulletApproved: false,
  accentHex: "2F5597",
  stylePrefix: "",
  formRows: Object.freeze(["Field A", "Field B", "Field C", "Field D"]),
  firstRowIndentDxa: 0,
});

function cleanHex(value) {
  return typeof value === "string" && /^[0-9A-F]{6}$/i.test(value) ? value.toUpperCase() : DEFAULT_PROFILE.accentHex;
}

export function buildProfile(features) {
  const merged = { ...DEFAULT_PROFILE, formRows: [...DEFAULT_PROFILE.formRows] };
  for (const feature of features) {
    const hints = feature.render_hints ?? {};
    if (typeof hints.documentLanguage === "string") merged.documentLanguage = hints.documentLanguage;
    if (Number.isInteger(hints.titleHalfPoints) && hints.titleHalfPoints >= 20 && hints.titleHalfPoints <= 144) merged.titleHalfPoints = hints.titleHalfPoints;
    if (typeof hints.bulletGlyph === "string" && hints.bulletGlyph.length > 0 && hints.bulletGlyph.length <= 4) merged.bulletGlyph = hints.bulletGlyph;
    if (typeof hints.bulletApproved === "boolean") merged.bulletApproved = hints.bulletApproved;
    if (typeof hints.accentHex === "string") merged.accentHex = cleanHex(hints.accentHex);
    if (typeof hints.stylePrefix === "string") merged.stylePrefix = hints.stylePrefix.slice(0, 40);
    if (Array.isArray(hints.formRows) && hints.formRows.length === 4 && hints.formRows.every((item) => typeof item === "string")) merged.formRows = [...hints.formRows];
    if (Number.isInteger(hints.firstRowIndentDxa) && hints.firstRowIndentDxa >= 0 && hints.firstRowIndentDxa <= 1440) merged.firstRowIndentDxa = hints.firstRowIndentDxa;
  }
  const diagnostics = features.filter((feature) => feature.execution).map((feature) => ({ requirement_id: feature.requirement_id, ...feature.execution }));
  const openQuestions = features.flatMap((feature) => Object.values(feature.ambiguity ?? {}).map((item) => ({ requirement_id: feature.requirement_id, ...item })));
  return Object.freeze({ ...merged, activeRequirementCount: features.length, diagnostics, openQuestions });
}
