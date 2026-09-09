export default Object.freeze({
  "requirement_id": "REQ_BOARD_MEETING_FIELD_ALIGNMENT",
  "state_id": "REQ_BOARD_MEETING_FIELD_ALIGNMENT_S003",
  "key": "board-meeting-field-alignment",
  "title": "Board Meeting Field Alignment",
  "family": "BOARD_MEETING_STRUCTURE",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE",
    "UI_UX"
  ],
  "contexts": [
    "BESTYRELSESMODE"
  ],
  "attributes": {
    "alignment_subject": "Item and Title",
    "must_align_with": [
      "Topic",
      "Proposal",
      "Start time"
    ]
  },
  "ambiguity": {
    "REQ_BOARD_MEETING_FIELD_ALIGNMENT_E003": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The freelancer cannot identify which Board Meeting field corresponds to Topic, so the fields involved in the required alignment cannot be applied unambiguously.",
      "source_event_id": "REQ_BOARD_MEETING_FIELD_ALIGNMENT_E003"
    }
  },
  "execution": {
    "status": "FAILED",
    "observed_behavior": "In the Board Meeting template, the Item and Title field does not line up with the Topic, Proposal, and Start time fields.",
    "source_event_id": "REQ_BOARD_MEETING_FIELD_ALIGNMENT_E002"
  },
  "supporting_event_ids": [
    "REQ_BOARD_MEETING_FIELD_ALIGNMENT_E001",
    "REQ_BOARD_MEETING_FIELD_ALIGNMENT_E002",
    "REQ_BOARD_MEETING_FIELD_ALIGNMENT_E003"
  ],
  "render_hints": {
    "formRows": [
      "Item and Title",
      "Topic",
      "Proposal",
      "Start time"
    ],
    "firstRowIndentDxa": 360
  }
});
