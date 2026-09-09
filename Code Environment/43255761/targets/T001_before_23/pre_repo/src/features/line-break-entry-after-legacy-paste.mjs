export default Object.freeze({
  "requirement_id": "REQ_POST_PASTE_LINE_BREAK_ENTRY",
  "state_id": "REQ_POST_PASTE_LINE_BREAK_ENTRY_S002",
  "key": "line-break-entry-after-legacy-paste",
  "title": "Line Break Entry After Legacy Paste",
  "family": "TEXT_ENTRY_BEHAVIOR",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "LEGACY_CONTENT_PASTE"
  ],
  "attributes": {
    "post_paste_manual_line_break_behavior": "Users can reliably insert manual line breaks after pasting legacy content."
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "Users are prevented from reliably inserting manual line breaks after pasted content.",
    "source_event_id": "REQ_POST_PASTE_LINE_BREAK_ENTRY_E002"
  },
  "supporting_event_ids": [
    "REQ_POST_PASTE_LINE_BREAK_ENTRY_E001",
    "REQ_POST_PASTE_LINE_BREAK_ENTRY_E002"
  ],
  "render_hints": {}
});
