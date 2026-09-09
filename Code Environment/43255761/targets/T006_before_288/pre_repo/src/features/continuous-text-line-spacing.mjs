export default Object.freeze({
  "requirement_id": "REQ_CONTINUOUS_TEXT_LINE_SPACING",
  "state_id": "REQ_CONTINUOUS_TEXT_LINE_SPACING_S002",
  "key": "continuous-text-line-spacing",
  "title": "Continuous Text Line Spacing",
  "family": "TEXT_ENTRY_BEHAVIOR",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "INDSTILLING",
    "VEJLEDNING",
    "CONTINUOUS_TEXT"
  ],
  "attributes": {
    "hard_return_line_spacing": "Hard returns in continuous text must use appropriate continuous-text line spacing rather than the larger spacing used between bullet points."
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "A normal hard return creates excessive spacing in continuous text, while Shift+Enter produces acceptable spacing.",
    "source_event_id": "REQ_CONTINUOUS_TEXT_LINE_SPACING_E002"
  },
  "supporting_event_ids": [
    "REQ_CONTINUOUS_TEXT_LINE_SPACING_E001",
    "REQ_CONTINUOUS_TEXT_LINE_SPACING_E002"
  ],
  "render_hints": {}
});
