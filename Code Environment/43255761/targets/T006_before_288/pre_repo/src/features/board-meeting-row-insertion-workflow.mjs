export default Object.freeze({
  "requirement_id": "REQ_BOARD_MEETING_ROW_WORKFLOW",
  "state_id": "REQ_BOARD_MEETING_ROW_WORKFLOW_S002",
  "key": "board-meeting-row-insertion-workflow",
  "title": "Board Meeting Row Insertion Workflow",
  "family": "BOARD_MEETING_STRUCTURE",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "BESTYRELSESMODE",
    "TABLE_ROWS"
  ],
  "attributes": {
    "topic_line_insertion_border_behavior": "Adding a line directly after a Topic must not create an additional horizontal line or border."
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "Customer testing found that adding a line directly after a Topic created an additional horizontal line or border, although line insertion elsewhere behaved correctly.",
    "source_event_id": "REQ_BOARD_MEETING_ROW_WORKFLOW_E002"
  },
  "supporting_event_ids": [
    "REQ_BOARD_MEETING_ROW_WORKFLOW_E001",
    "REQ_BOARD_MEETING_ROW_WORKFLOW_E002"
  ],
  "render_hints": {}
});
