export default Object.freeze({
  "requirement_id": "REQ_DISTRIBUTION_WARNING",
  "state_id": "REQ_DISTRIBUTION_WARNING_S002",
  "key": "confidential-distribution-warning",
  "title": "Confidential Distribution Warning",
  "family": "REPORT_CONTENT_SECTIONS",
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_TEMPLATE"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "FINAL_PAGE"
  ],
  "attributes": {
    "warning_presence": "retain a distribution warning on the final page",
    "warning_message": "the report is confidential and intended for limited distribution",
    "visual_treatment": "refined and visually subordinate to the page content"
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The final-page warning's red block was visually too heavy.",
    "source_event_id": "REQ_DISTRIBUTION_WARNING_E002"
  },
  "supporting_event_ids": [
    "REQ_DISTRIBUTION_WARNING_E001",
    "REQ_DISTRIBUTION_WARNING_E002"
  ],
  "render_hints": {
    "warningEnabled": true,
    "warningText": "the report is confidential and intended for limited distribution",
    "warningStyle": "heavy"
  }
});
