export default Object.freeze({
  "requirement_id": "REQ_SCORING_SUMMARY_TABLE",
  "state_id": "REQ_SCORING_SUMMARY_TABLE_S002",
  "key": "scoring-summary-table",
  "title": "Scoring Summary Table",
  "family": "REPORT_CONTENT_SECTIONS",
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_TEMPLATE"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "SCORING_SUMMARY",
    "RR01",
    "RR02",
    "RR03",
    "RR04"
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
    "REQ_SCORING_SUMMARY_TABLE_E001",
    "REQ_SCORING_SUMMARY_TABLE_E002"
  ],
  "render_hints": {}
});
