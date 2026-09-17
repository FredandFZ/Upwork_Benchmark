export default Object.freeze({
  "requirement_id": "REQ_FRONT_PAGE_RESULT_DASHBOARD",
  "state_id": "REQ_FRONT_PAGE_RESULT_DASHBOARD_S003",
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
    "dashboard_prominence": "prominent",
    "displayed_result_fields": [
      "vehicle_security_score",
      "risk_band",
      "exposure_level",
      "priority_level",
      "main_rating_reason",
      "primary_weaknesses"
    ],
    "result_visibility": "immediately clear when the customer opens the report",
    "dashboard_visual_reference": "the first supplied image"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_FRONT_PAGE_RESULT_DASHBOARD_E001",
    "REQ_FRONT_PAGE_RESULT_DASHBOARD_E002",
    "REQ_FRONT_PAGE_RESULT_DASHBOARD_E003"
  ],
  "render_hints": {
    "scoreHeading": "Security Score",
    "scoreFontSize": 34,
    "dashboardFailed": false
  }
});
