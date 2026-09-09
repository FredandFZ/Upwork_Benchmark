export default Object.freeze({
  "requirement_id": "REQ_STYLE_TYPOGRAPHY",
  "state_id": "REQ_STYLE_TYPOGRAPHY_S005",
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
    "heading_3_bold": true,
    "title_font_size": "28 pt",
    "caption_text_targets": [
      "images",
      "tables"
    ],
    "caption_text_size_and_line_height": "7/10 pt",
    "caption_text_italic": true,
    "caption_text_font_family": "Century Gothic"
  },
  "ambiguity": {
    "REQ_STYLE_TYPOGRAPHY_E002": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The intended size relationship between Title and Heading 1, and whether either style should be bold, require client clarification.",
      "source_event_id": "REQ_STYLE_TYPOGRAPHY_E002"
    }
  },
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The required 7/10 pt italic Century Gothic caption typography for image and table text is missing from New Styles.docx.",
    "source_event_id": "REQ_STYLE_TYPOGRAPHY_E005"
  },
  "supporting_event_ids": [
    "REQ_STYLE_TYPOGRAPHY_E001",
    "REQ_STYLE_TYPOGRAPHY_E002",
    "REQ_STYLE_TYPOGRAPHY_E003",
    "REQ_STYLE_TYPOGRAPHY_E004",
    "REQ_STYLE_TYPOGRAPHY_E005"
  ],
  "render_hints": {
    "titleHalfPoints": 56
  }
});
