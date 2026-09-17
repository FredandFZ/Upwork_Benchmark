const DEFAULT_PROFILE = Object.freeze({
  projectTitle: "Generic Electronics Design",
  boardVariant: "generic-board",
  boardCount: 1,
  boardWidthMm: 80,
  boardHeightMm: 50,
  mountingHoleCount: 4,
  connectorTopAligned: false,
  lowerConnectorsUpward: false,
  batteryProtectionSpecified: false,
  overchargeCutoffSpecified: false,
  batteryNtcContact: false,
  batteryConnectorOrientation: "unspecified",
  fullPinBreakout: false,
  breakoutPinCount: null,
  throughHoleBreakout: false,
  touchInputCount: 0,
  pirInputPresent: false,
  panelInputCount: 0,
  inputBiasSpecified: false,
  vrtcHandling: "unspecified",
  vbackupAccess: false,
  vbackupLocationSpecified: false,
  bomStatus: "not-specified",
});

export function buildProfile(features) {
  const merged = { ...DEFAULT_PROFILE };
  for (const feature of features) {
    const hints = feature.render_hints ?? {};
    for (const key of ["projectTitle", "boardVariant", "batteryConnectorOrientation", "vrtcHandling", "bomStatus"]) {
      if (typeof hints[key] === "string") merged[key] = hints[key].slice(0, 160);
    }
    for (const key of ["connectorTopAligned", "lowerConnectorsUpward", "batteryProtectionSpecified", "overchargeCutoffSpecified", "batteryNtcContact", "fullPinBreakout", "throughHoleBreakout", "pirInputPresent", "inputBiasSpecified", "vbackupAccess", "vbackupLocationSpecified"]) {
      if (typeof hints[key] === "boolean") merged[key] = hints[key];
    }
    for (const key of ["boardCount", "boardWidthMm", "boardHeightMm", "mountingHoleCount", "breakoutPinCount", "touchInputCount", "panelInputCount"]) {
      if (Number.isFinite(hints[key]) && hints[key] >= 0) merged[key] = hints[key];
    }
  }
  const familyCounts = Object.fromEntries([...new Set(features.map((feature) => feature.family))].sort().map((family) => [family, features.filter((feature) => feature.family === family).length]));
  const diagnostics = features.filter((feature) => feature.execution).map((feature) => ({ requirement_id: feature.requirement_id, ...feature.execution }));
  const openQuestions = features.flatMap((feature) => Object.values(feature.ambiguity ?? {}).map((item) => ({ requirement_id: feature.requirement_id, ...item })));
  return Object.freeze({ ...merged, activeRequirementCount: features.length, familyCounts, diagnostics, openQuestions });
}
