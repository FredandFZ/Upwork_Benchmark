export default Object.freeze({
  "requirement_id": "REQ_THEME_COLOR_PALETTE",
  "state_id": "REQ_THEME_COLOR_PALETTE_S004",
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
    "required_theme_colors_included": true,
    "available_color_choices": "only approved theme colors"
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "Customer feedback reports that the Master template exposes inappropriate extra colors as available choices.",
    "source_event_id": "REQ_THEME_COLOR_PALETTE_E004"
  },
  "supporting_event_ids": [
    "REQ_THEME_COLOR_PALETTE_E001",
    "REQ_THEME_COLOR_PALETTE_E003",
    "REQ_THEME_COLOR_PALETTE_E004"
  ],
  "render_hints": {}
});
