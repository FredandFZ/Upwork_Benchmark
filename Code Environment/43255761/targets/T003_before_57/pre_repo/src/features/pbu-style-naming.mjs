export default Object.freeze({
  "requirement_id": "REQ_STYLE_NAMING",
  "state_id": "REQ_STYLE_NAMING_S002",
  "key": "pbu-style-naming",
  "title": "PBU Style Naming",
  "family": "WORD_STYLE_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "ALL_WORD_TEMPLATES"
  ],
  "attributes": {
    "style_name_prefix": "PBU -",
    "applicability_condition": "Rename all applicable active template styles when doing so helps resolve copy-paste issues.",
    "covered_style_categories": [
      "headings",
      "body text",
      "quotes",
      "list styles",
      "table-related styles",
      "other active template styles"
    ],
    "style_name_language": "Danish"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_STYLE_NAMING_E001",
    "REQ_STYLE_NAMING_E002"
  ],
  "render_hints": {
    "stylePrefix": "PBU -"
  }
});
