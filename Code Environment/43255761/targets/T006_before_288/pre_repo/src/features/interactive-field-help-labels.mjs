export default Object.freeze({
  "requirement_id": "REQ_FIELD_HELP_LABELS",
  "state_id": "REQ_FIELD_HELP_LABELS_S008",
  "key": "interactive-field-help-labels",
  "title": "Interactive Field Help Labels",
  "family": "INTERACTIVE_FIELDS",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE",
    "UI_UX"
  ],
  "contexts": [
    "INTERACTIVE_FIELDS",
    "ALL_CONTROL_FIELDS"
  ],
  "attributes": {
    "help_label_language": "Danish",
    "help_labels_unique_per_field": true,
    "label_field_content_relationship": "label must match the text shown inside the field",
    "date_field_help_text": "Klik for at indsætte en dato",
    "subject_field_help_text": "Indsæt dagsorden",
    "hover_help_behavior": "label remains available on hover after field content is replaced",
    "help_text_locations": [
      "label",
      "field"
    ]
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_FIELD_HELP_LABELS_E001",
    "REQ_FIELD_HELP_LABELS_E002",
    "REQ_FIELD_HELP_LABELS_E003",
    "REQ_FIELD_HELP_LABELS_E004",
    "REQ_FIELD_HELP_LABELS_E006",
    "REQ_FIELD_HELP_LABELS_E007",
    "REQ_FIELD_HELP_LABELS_E008"
  ],
  "render_hints": {}
});
