export default Object.freeze({
  "requirement_id": "REQ_THEME_COLOR_PALETTE",
  "state_id": "REQ_THEME_COLOR_PALETTE_S002",
  "key": "controlled-theme-color-palette",
  "title": "Controlled Theme Color Palette",
  "family": "WORD_STYLE_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE",
    "UI_UX"
  ],
  "contexts": [
    "MASTER_TEMPLATE"
  ],
  "attributes": {
    "required_theme_colors_included": true
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The client reports that the theme colors are missing from New Styles.docx.",
    "source_event_id": "REQ_THEME_COLOR_PALETTE_E002"
  },
  "supporting_event_ids": [
    "REQ_THEME_COLOR_PALETTE_E001",
    "REQ_THEME_COLOR_PALETTE_E002"
  ],
  "render_hints": {}
});
