import { writeZip } from "./zip.mjs";

function xml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&apos;");
}

function paragraph(text, { style = null, bold = false, color = null, before = 0, after = 120, left = 0, numId = null } = {}) {
  const pPr = [style ? `<w:pStyle w:val="${xml(style)}"/>` : "", left ? `<w:ind w:left="${left}"/>` : "", numId ? `<w:numPr><w:ilvl w:val="0"/><w:numId w:val="${numId}"/></w:numPr>` : "", `<w:spacing w:before="${before}" w:after="${after}"/>`].join("");
  const rPr = [bold ? "<w:b/>" : "", color ? `<w:color w:val="${xml(color)}"/>` : ""].join("");
  return `<w:p><w:pPr>${pPr}</w:pPr><w:r><w:rPr>${rPr}</w:rPr><w:t xml:space="preserve">${xml(text)}</w:t></w:r></w:p>`;
}

function tableCell(text, width, { shade = null, bold = false, left = 0 } = {}) {
  const fill = shade ? `<w:shd w:val="clear" w:color="auto" w:fill="${xml(shade)}"/>` : "";
  return `<w:tc><w:tcPr><w:tcW w:w="${width}" w:type="dxa"/>${fill}<w:tcMar><w:top w:w="120" w:type="dxa"/><w:left w:w="120" w:type="dxa"/><w:bottom w:w="120" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tcMar><w:vAlign w:val="center"/></w:tcPr>${paragraph(text, { bold, left, after: 0 })}</w:tc>`;
}

function formTable(profile) {
  const rows = profile.formRows.map((label, index) => `<w:tr>${tableCell(label, 3000, { shade: index === 0 ? "EAF0F8" : null, bold: true, left: index === 0 ? profile.firstRowIndentDxa : 0 })}${tableCell("Editable response area", 6360)}</w:tr>`).join("");
  return `<w:tbl><w:tblPr><w:tblW w:w="9360" w:type="dxa"/><w:tblInd w:w="120" w:type="dxa"/><w:tblLayout w:type="fixed"/><w:tblBorders><w:top w:val="single" w:sz="6" w:color="B7C9E2"/><w:left w:val="single" w:sz="6" w:color="B7C9E2"/><w:bottom w:val="single" w:sz="6" w:color="B7C9E2"/><w:right w:val="single" w:sz="6" w:color="B7C9E2"/><w:insideH w:val="single" w:sz="4" w:color="D9E2F3"/><w:insideV w:val="single" w:sz="4" w:color="D9E2F3"/></w:tblBorders></w:tblPr><w:tblGrid><w:gridCol w:w="3000"/><w:gridCol w:w="6360"/></w:tblGrid>${rows}</w:tbl>`;
}

function contentTypes() {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/><Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>`;
}

function styles(profile) {
  const lang = xml(profile.documentLanguage);
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="${lang}"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:before="0" w:after="180"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:b/><w:color w:val="${profile.accentHex}"/><w:sz w:val="${profile.titleHalfPoints}"/><w:szCs w:val="${profile.titleHalfPoints}"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="180" w:after="90"/></w:pPr><w:rPr><w:b/><w:color w:val="${profile.accentHex}"/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style></w:styles>`;
}

function numbering(profile) {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="${xml(profile.bulletGlyph)}"/><w:lvlJc w:val="left"/><w:pPr><w:tabs><w:tab w:val="num" w:pos="720"/></w:tabs><w:ind w:left="720" w:hanging="360"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>`;
}

function documentXml(profile, label) {
  const status = profile.bulletApproved ? "matched" : "pending";
  const prefix = profile.stylePrefix ? `Style prefix: ${profile.stylePrefix}` : "Style prefix: default";
  const body = [
    paragraph(label, { style: "Title" }),
    paragraph("Deterministic executable preview generated from the reconstructed requirement state."),
    paragraph("State overview", { style: "Heading1" }),
    paragraph(`${profile.activeRequirementCount} active requirement states · ${profile.openQuestions.length} open questions · ${profile.diagnostics.length} runtime diagnostics`, { color: profile.accentHex }),
    paragraph(prefix),
    paragraph("List preview", { style: "Heading1" }),
    paragraph("Clear hierarchy and stable indentation", { numId: 1, after: 60 }),
    paragraph("Wrapped lines remain aligned with list text", { numId: 1, after: 60 }),
    paragraph(`Reference styling: ${status}`, { numId: 1, after: 120 }),
    paragraph("Structured fields", { style: "Heading1" }),
    formTable(profile),
    paragraph("Generated locally with no external services.", { before: 180, after: 0, color: "666666" }),
    `<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>`,
  ].join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${body}</w:body></w:document>`;
}

export function documentEntries(profile, label = "Executable Word template") {
  return new Map([
    ["[Content_Types].xml", contentTypes()],
    ["_rels/.rels", `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>`],
    ["docProps/core.xml", `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>${xml(label)}</dc:title><dc:creator>Reconstruction Harness</dc:creator><cp:lastModifiedBy>Reconstruction Harness</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">2000-01-01T00:00:00Z</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">2000-01-01T00:00:00Z</dcterms:modified></cp:coreProperties>`],
    ["docProps/app.xml", `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>Reconstruction Harness</Application><AppVersion>1.0</AppVersion></Properties>`],
    ["word/_rels/document.xml.rels", `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/></Relationships>`],
    ["word/document.xml", documentXml(profile, label)],
    ["word/styles.xml", styles(profile)],
    ["word/numbering.xml", numbering(profile)],
    ["word/settings.xml", `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:zoom w:percent="100"/><w:defaultTabStop w:val="720"/><w:themeFontLang w:val="${xml(profile.documentLanguage)}"/></w:settings>`],
  ]);
}

export function writeDocument(filePath, profile, label) {
  writeZip(filePath, documentEntries(profile, label));
}
