export default Object.freeze({
  "requirement_id": "REQ_SCANNABLE_RESULT_EXPLANATION",
  "state_id": "REQ_SCANNABLE_RESULT_EXPLANATION_S004",
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
    "presentation_goal": "Make the customer's result immediately clear when the report is opened.",
    "presentation_format": "Short bullet points that are easy to scan.",
    "page_one_detail_level": "Concise enough to make page one quick and easy to read."
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The reviewed dark blue \"What Caused This Result\" panel contained too much text for the page-one explanation to be scanned quickly.",
    "source_event_id": "REQ_SCANNABLE_RESULT_EXPLANATION_E004"
  },
  "supporting_event_ids": [
    "REQ_SCANNABLE_RESULT_EXPLANATION_E001",
    "REQ_SCANNABLE_RESULT_EXPLANATION_E002",
    "REQ_SCANNABLE_RESULT_EXPLANATION_E003",
    "REQ_SCANNABLE_RESULT_EXPLANATION_E004"
  ],
  "render_hints": {
    "explanationDense": true,
    "explanationItems": [
      "Extended explanation line one",
      "Extended explanation line two",
      "Extended explanation line three",
      "Extended explanation line four",
      "Extended explanation line five",
      "Extended explanation line six"
    ]
  }
});
