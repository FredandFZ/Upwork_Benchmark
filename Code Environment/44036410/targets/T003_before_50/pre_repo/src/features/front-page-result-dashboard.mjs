export default Object.freeze({
  "requirement_id": "REQ_FRONT_PAGE_RESULT_DASHBOARD",
  "state_id": "REQ_FRONT_PAGE_RESULT_DASHBOARD_S005",
  "key": "front-page-result-dashboard",
  "title": "Front-Page Result Dashboard",
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
    "dashboard_prominence": "slightly enlarge the score and add more surrounding space so it functions as the main dashboard result",
    "displayed_result_fields": [
      "vehicle_security_score",
      "risk_band",
      "exposure_level",
      "priority_level",
      "main_rating_reason",
      "primary_weaknesses"
    ],
    "result_visibility": "immediately show both the score and risk outcome",
    "dashboard_visual_reference": "the first supplied image",
    "score_heading": "Vehicle Security Score"
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "Review of the revised report found that the front-page score lacked sufficient prominence and used the incomplete heading \"Security Score\".",
    "source_event_id": "REQ_FRONT_PAGE_RESULT_DASHBOARD_E005"
  },
  "supporting_event_ids": [
    "REQ_FRONT_PAGE_RESULT_DASHBOARD_E001",
    "REQ_FRONT_PAGE_RESULT_DASHBOARD_E002",
    "REQ_FRONT_PAGE_RESULT_DASHBOARD_E003",
    "REQ_FRONT_PAGE_RESULT_DASHBOARD_E004",
    "REQ_FRONT_PAGE_RESULT_DASHBOARD_E005"
  ],
  "render_hints": {
    "scoreHeading": "Vehicle Security Score",
    "scoreFontSize": 46,
    "dashboardFailed": true
  }
});
