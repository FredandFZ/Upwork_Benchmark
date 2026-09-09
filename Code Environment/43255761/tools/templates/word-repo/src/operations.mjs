export function resolveTitleStyle(profile) {
  return Object.freeze({ fontFamily: "Arial", sizePoints: profile.titleHalfPoints / 2, bold: true, colorHex: profile.accentHex });
}

export function resolveBulletProfile(profile, referenceProfile = null) {
  if (profile.bulletApproved && referenceProfile) return Object.freeze({ ...referenceProfile, source: "approved-reference" });
  return Object.freeze({ glyph: profile.bulletGlyph, proportionalToText: true, verticallyCentered: true, source: profile.bulletApproved ? "approved-state" : "baseline" });
}

export function fieldAnchors(profile) {
  const baseX = 1560;
  return profile.formRows.map((label, index) => Object.freeze({ label, xDxa: baseX + (index === 0 ? profile.firstRowIndentDxa : 0), gridColumn: 0 }));
}

export function resolveField(profile, label) {
  const normalized = String(label).trim().toLocaleLowerCase("en");
  const index = profile.formRows.findIndex((item) => item.toLocaleLowerCase("en") === normalized);
  return index < 0 ? null : Object.freeze({ index, label: profile.formRows[index], anchor: fieldAnchors(profile)[index] });
}
