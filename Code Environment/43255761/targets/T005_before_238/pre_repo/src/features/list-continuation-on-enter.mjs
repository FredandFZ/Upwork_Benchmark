export default Object.freeze({
  "requirement_id": "REQ_LIST_CONTINUATION_ON_ENTER",
  "state_id": "REQ_LIST_CONTINUATION_ON_ENTER_S001",
  "key": "list-continuation-on-enter",
  "title": "List Continuation on Enter",
  "family": "LIST_BEHAVIOR",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "INDSTILLING",
    "STRUCTURED_LIST_FIELDS"
  ],
  "attributes": {
    "enter_key_behavior": "automatically creates the next bullet"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_LIST_CONTINUATION_ON_ENTER_E001"
  ],
  "render_hints": {}
});
