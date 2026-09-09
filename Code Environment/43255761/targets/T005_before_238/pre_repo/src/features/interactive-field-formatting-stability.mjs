export default Object.freeze({
  "requirement_id": "REQ_FIELD_FORMATTING_STABILITY",
  "state_id": "REQ_FIELD_FORMATTING_STABILITY_S002",
  "key": "interactive-field-formatting-stability",
  "title": "Interactive Field Formatting Stability",
  "family": "INTERACTIVE_FIELDS",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "INTERACTIVE_FIELDS",
    "TITLE_FIELDS"
  ],
  "attributes": {
    "title_field_formatting_preservation": true
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The Title field loses its intended formatting during use.",
    "source_event_id": "REQ_FIELD_FORMATTING_STABILITY_E002"
  },
  "supporting_event_ids": [
    "REQ_FIELD_FORMATTING_STABILITY_E001",
    "REQ_FIELD_FORMATTING_STABILITY_E002"
  ],
  "render_hints": {}
});
