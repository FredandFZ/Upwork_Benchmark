export default Object.freeze({
  "requirement_id": "REQ_STYLE_TYPOGRAPHY",
  "state_id": "REQ_STYLE_TYPOGRAPHY_S002",
  "key": "template-style-typography",
  "title": "Template Style Typography",
  "family": "WORD_STYLE_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE",
    "UI_UX"
  ],
  "contexts": [
    "ALL_WORD_TEMPLATES"
  ],
  "attributes": {
    "heading_3_font_size": "retain existing size",
    "heading_3_bold": true
  },
  "ambiguity": {
    "REQ_STYLE_TYPOGRAPHY_E002": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The intended size relationship between Title and Heading 1, and whether either style should be bold, require client clarification.",
      "source_event_id": "REQ_STYLE_TYPOGRAPHY_E002"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_STYLE_TYPOGRAPHY_E001",
    "REQ_STYLE_TYPOGRAPHY_E002"
  ],
  "render_hints": {}
});
