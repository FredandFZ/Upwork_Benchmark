export default Object.freeze({
  "requirement_id": "REQ_NUMBERED_LIST_ALIGNMENT",
  "state_id": "REQ_NUMBERED_LIST_ALIGNMENT_S003",
  "key": "numbered-list-alignment",
  "title": "Numbered List Alignment",
  "family": "LIST_BEHAVIOR",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "NUMBERED_LISTS",
    "ALL_WORD_TEMPLATES"
  ],
  "attributes": {
    "alignment_across_list_levels": "Numbered and multilevel lists must maintain consistent alignment across list levels and remain orderly and usable.",
    "multi_digit_alignment": "Numbered-list alignment must remain intact when the list reaches item 10."
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The numbered-list alignment breaks when numbering reaches item 10.",
    "source_event_id": "REQ_NUMBERED_LIST_ALIGNMENT_E003"
  },
  "supporting_event_ids": [
    "REQ_NUMBERED_LIST_ALIGNMENT_E001",
    "REQ_NUMBERED_LIST_ALIGNMENT_E002",
    "REQ_NUMBERED_LIST_ALIGNMENT_E003"
  ],
  "render_hints": {}
});
