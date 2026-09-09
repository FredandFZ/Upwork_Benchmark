export default Object.freeze({
  "requirement_id": "REQ_FILLABLE_FIELD_VISUAL_CUES",
  "state_id": "REQ_FILLABLE_FIELD_VISUAL_CUES_S002",
  "key": "visible-fillable-field-cues",
  "title": "Visible Fillable Field Cues",
  "family": "INTERACTIVE_FIELDS",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE",
    "UI_UX"
  ],
  "contexts": [
    "INTERACTIVE_FIELDS",
    "INDSTILLING"
  ],
  "attributes": {
    "field_identification_method": "grey field appearance",
    "cue_purpose": "indicate where the user needs to provide input"
  },
  "ambiguity": {
    "REQ_FILLABLE_FIELD_VISUAL_CUES_E002": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The client prefers grey fields as visible input cues, but the freelancer reports that these legacy fields depend on password protection, leaving the appropriate cue mechanism unresolved.",
      "source_event_id": "REQ_FILLABLE_FIELD_VISUAL_CUES_E002"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_FILLABLE_FIELD_VISUAL_CUES_E001",
    "REQ_FILLABLE_FIELD_VISUAL_CUES_E002"
  ],
  "render_hints": {}
});
