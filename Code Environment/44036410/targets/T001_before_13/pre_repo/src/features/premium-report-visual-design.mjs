export default Object.freeze({
  "requirement_id": "REQ_PREMIUM_REPORT_VISUAL_DESIGN",
  "state_id": "REQ_PREMIUM_REPORT_VISUAL_DESIGN_S001",
  "key": "premium-report-visual-design",
  "title": "Premium Report Visual Design",
  "family": null,
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_DESIGN"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT"
  ],
  "attributes": {
    "visual_quality_standard": "Premium, polished presentation resembling a professionally produced paid assessment",
    "design_objective": "Enhance the existing report's design, structure, and layout"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PREMIUM_REPORT_VISUAL_DESIGN_E001"
  ],
  "render_hints": {
    "premium": true,
    "reportTitle": "Vehicle Security Assessment Report",
    "reportCodeLabel": "Report code",
    "dateLabel": "Assessment Date",
    "riskHeading": "Risk Band",
    "dashboardReasonHeading": "What caused this result",
    "detailsHeading": "Assessment details",
    "subjectLabel": "Vehicle group",
    "subjectValue": "Customer-assessed vehicle group",
    "contextHeading": "Risk context",
    "priorityHeading": "Priority upgrade path"
  }
});
