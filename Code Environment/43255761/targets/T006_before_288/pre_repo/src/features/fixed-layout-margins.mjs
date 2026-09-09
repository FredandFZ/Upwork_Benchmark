export default Object.freeze({
  "requirement_id": "REQ_FIXED_LAYOUT_MARGINS",
  "state_id": "REQ_FIXED_LAYOUT_MARGINS_S003",
  "key": "fixed-layout-margins",
  "title": "Fixed Layout Margins",
  "family": "DOCUMENT_LAYOUT",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE",
    "UI_UX"
  ],
  "contexts": [
    "VEJLEDNING"
  ],
  "attributes": {
    "short_description_margin_behavior": "Margins beneath the short-description section must remain fixed so content growth does not progressively cut off the pencil icon."
  },
  "ambiguity": null,
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "The freelancer reports that the margins will no longer collapse as they did before.",
    "source_event_id": "REQ_FIXED_LAYOUT_MARGINS_E003"
  },
  "supporting_event_ids": [
    "REQ_FIXED_LAYOUT_MARGINS_E001",
    "REQ_FIXED_LAYOUT_MARGINS_E003"
  ],
  "render_hints": {}
});
