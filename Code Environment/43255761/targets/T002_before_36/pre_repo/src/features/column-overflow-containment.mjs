export default Object.freeze({
  "requirement_id": "REQ_COLUMN_OVERFLOW_CONTAINMENT",
  "state_id": "REQ_COLUMN_OVERFLOW_CONTAINMENT_S001",
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
    "right_column_overflow_constraint": "The right-hand column must remain within the page margins when content is pasted."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_COLUMN_OVERFLOW_CONTAINMENT_E001"
  ],
  "render_hints": {}
});
