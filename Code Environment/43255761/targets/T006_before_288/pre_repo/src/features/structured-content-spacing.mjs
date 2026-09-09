export default Object.freeze({
  "requirement_id": "REQ_STYLE_SPACING",
  "state_id": "REQ_STYLE_SPACING_S004",
  "key": "structured-content-spacing",
  "title": "Structured Content Spacing",
  "family": "WORD_STYLE_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE",
    "UI_UX"
  ],
  "contexts": [
    "PROPOSAL_TEMPLATE"
  ],
  "attributes": {
    "text_to_right_line_spacing": "Add a little spacing after the text so it does not touch the line on the right."
  },
  "ambiguity": null,
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Following the reported spacing failure, the freelancer claims that spacing has been configured at both the top and bottom.",
    "source_event_id": "REQ_STYLE_SPACING_E004"
  },
  "supporting_event_ids": [
    "REQ_STYLE_SPACING_E001",
    "REQ_STYLE_SPACING_E004"
  ],
  "render_hints": {}
});
