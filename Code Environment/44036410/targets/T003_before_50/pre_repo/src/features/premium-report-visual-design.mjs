export default Object.freeze({
  "requirement_id": "REQ_PREMIUM_REPORT_VISUAL_DESIGN",
  "state_id": "REQ_PREMIUM_REPORT_VISUAL_DESIGN_S005",
  "key": "premium-report-visual-design",
  "title": "Premium Report Visual Design",
  "family": null,
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_DESIGN"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "RR01",
    "RR02",
    "RR03",
    "RR04"
  ],
  "attributes": {
    "visual_quality_standard": "Premium, polished presentation resembling a professionally produced paid assessment",
    "design_objective": "Enhance the existing report's design, structure, and layout",
    "cross_variant_visual_consistency": "Apply the same design across all four report versions",
    "design_direction": "Retain the revised general appearance and style rather than redesigning the report from the beginning",
    "final_refinement_focus": [
      "readability",
      "consistency",
      "stronger commercial finish"
    ]
  },
  "ambiguity": null,
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer reports revising the report design according to the client's requested refinements.",
    "source_event_id": "REQ_PREMIUM_REPORT_VISUAL_DESIGN_E005"
  },
  "supporting_event_ids": [
    "REQ_PREMIUM_REPORT_VISUAL_DESIGN_E001",
    "REQ_PREMIUM_REPORT_VISUAL_DESIGN_E002",
    "REQ_PREMIUM_REPORT_VISUAL_DESIGN_E004",
    "REQ_PREMIUM_REPORT_VISUAL_DESIGN_E005"
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
