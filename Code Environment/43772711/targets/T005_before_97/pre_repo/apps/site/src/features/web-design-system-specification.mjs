export default Object.freeze({
  "key": "web-design-system-specification",
  "title": "Web Design-System Specification",
  "family": "WEB_IMPLEMENTATION_FOUNDATION",
  "lifecycle": "ACTIVE",
  "components": [
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "DESIGN_SYSTEM",
    "IMPLEMENTATION_HANDOFF"
  ],
  "configuration": {
    "token_sheet_contents": [
      "colors in hex with background, text, border, and accent usage",
      "type scale with family, weight, size, line height, and tracking per style",
      "spacing scale",
      "radii",
      "border widths"
    ],
    "font_file_format": ".woff2",
    "font_metadata": [
      "exact family names",
      "weights actually in use"
    ],
    "max_content_width_specification": "one confirmed numeric value"
  },
  "ambiguities": [
    {
      "status": "OPEN",
      "dimension": "SCOPE",
      "description": "It remains unresolved whether the requested design-system specification should be incorporated into the existing brand-guide document."
    }
  ],
  "execution": null
});
