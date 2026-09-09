export default Object.freeze({
  "requirement_id": "REQ_TABLE_COLUMN_LAYOUT_INTEGRITY",
  "state_id": "REQ_TABLE_COLUMN_LAYOUT_INTEGRITY_S003",
  "key": "table-paste-layout-stability",
  "title": "Table Paste Layout Stability",
  "family": "TABLE_BEHAVIOR",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE"
  ],
  "contexts": [
    "TABLES",
    "MULTI_COLUMN_LAYOUTS"
  ],
  "attributes": {
    "table_layout_during_paste": "Table layouts must remain fixed and dependable when content is pasted.",
    "right_column_boundary": "The right column must remain within the page margins when content is pasted."
  },
  "ambiguity": {
    "REQ_TABLE_COLUMN_LAYOUT_INTEGRITY_E003": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The freelancer states that styling a table is possible but correcting the rightward shift of a pasted table is not, conflicting with the client-required layout stability.",
      "source_event_id": "REQ_TABLE_COLUMN_LAYOUT_INTEGRITY_E003"
    }
  },
  "execution": {
    "status": "FAILED",
    "observed_behavior": "Users encounter table damage and the right-hand column shifts beyond the page margins when content is pasted.",
    "source_event_id": "REQ_TABLE_COLUMN_LAYOUT_INTEGRITY_E002"
  },
  "supporting_event_ids": [
    "REQ_TABLE_COLUMN_LAYOUT_INTEGRITY_E001",
    "REQ_TABLE_COLUMN_LAYOUT_INTEGRITY_E002",
    "REQ_TABLE_COLUMN_LAYOUT_INTEGRITY_E003"
  ],
  "render_hints": {}
});
