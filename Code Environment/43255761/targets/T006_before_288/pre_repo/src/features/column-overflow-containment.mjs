export default Object.freeze({
  "requirement_id": "REQ_COLUMN_OVERFLOW_CONTAINMENT",
  "state_id": "REQ_COLUMN_OVERFLOW_CONTAINMENT_S003",
  "key": "column-overflow-containment",
  "title": "Column Overflow Containment",
  "family": "DOCUMENT_LAYOUT",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE",
    "UI_UX"
  ],
  "contexts": [
    "MULTI_COLUMN_LAYOUTS",
    "LEGACY_COPY_PASTE"
  ],
  "attributes": {
    "right_column_overflow_constraint": "The right-hand column must remain within the page margins when content is pasted.",
    "left_text_box_overflow_behavior": "When left-side text boxes run out of room, words must wrap automatically instead of pushing the right-hand column farther right."
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "When the left-side text boxes, including the headline, run out of room, they fail to wrap words automatically and instead push the right-hand column farther to the right.",
    "source_event_id": "REQ_COLUMN_OVERFLOW_CONTAINMENT_E003"
  },
  "supporting_event_ids": [
    "REQ_COLUMN_OVERFLOW_CONTAINMENT_E001",
    "REQ_COLUMN_OVERFLOW_CONTAINMENT_E002",
    "REQ_COLUMN_OVERFLOW_CONTAINMENT_E003"
  ],
  "render_hints": {}
});
