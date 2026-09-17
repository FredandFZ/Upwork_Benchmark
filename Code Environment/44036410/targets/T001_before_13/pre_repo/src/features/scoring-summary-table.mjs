export default Object.freeze({
  "requirement_id": "REQ_SCORING_SUMMARY_TABLE",
  "state_id": "REQ_SCORING_SUMMARY_TABLE_S001",
  "key": "scoring-summary-table",
  "title": "Scoring Summary Table",
  "family": "REPORT_CONTENT_SECTIONS",
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_TEMPLATE"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "SCORING_SUMMARY"
  ],
  "attributes": {
    "presentation": "easy-to-understand scoring table",
    "fields": [
      "main scoring category",
      "maximum score",
      "customer score",
      "total score"
    ],
    "purpose": "provide a professional and transparent assessment summary"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_SCORING_SUMMARY_TABLE_E001"
  ],
  "render_hints": {}
});
