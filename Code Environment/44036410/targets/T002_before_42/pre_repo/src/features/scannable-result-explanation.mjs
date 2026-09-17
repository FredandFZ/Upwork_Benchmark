export default Object.freeze({
  "requirement_id": "REQ_SCANNABLE_RESULT_EXPLANATION",
  "state_id": "REQ_SCANNABLE_RESULT_EXPLANATION_S002",
  "key": "scannable-result-explanation",
  "title": "Scannable Result Explanation",
  "family": "FRONT_PAGE_PRESENTATION",
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_TEMPLATE"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "FRONT_PAGE",
    "RR01",
    "RR02",
    "RR03",
    "RR04"
  ],
  "attributes": {
    "front_page_explanation_content": [
      "main reason for the rating",
      "primary weaknesses"
    ],
    "presentation_goal": "Make the customer's result immediately clear when the report is opened."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_SCANNABLE_RESULT_EXPLANATION_E001",
    "REQ_SCANNABLE_RESULT_EXPLANATION_E002"
  ],
  "render_hints": {
    "explanationDense": false,
    "explanationItems": [
      "Primary result reason",
      "Main exposure",
      "Priority action"
    ]
  }
});
