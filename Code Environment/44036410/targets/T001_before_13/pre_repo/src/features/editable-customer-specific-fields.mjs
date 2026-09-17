export default Object.freeze({
  "requirement_id": "REQ_EDITABLE_CUSTOMER_FIELDS",
  "state_id": "REQ_EDITABLE_CUSTOMER_FIELDS_S001",
  "key": "editable-customer-specific-fields",
  "title": "Editable Customer-Specific Fields",
  "family": null,
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_TEMPLATE"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "CUSTOMER_CUSTOMIZATION"
  ],
  "attributes": {
    "customer_specific_fields": [
      "vehicle_registration",
      "assessment_date",
      "report_id",
      "vehicle_group",
      "security_score",
      "risk_band",
      "category_scores",
      "weaknesses",
      "recommendations",
      "customer_specific_notes"
    ],
    "editing_expectation": "The report templates must remain straightforward to edit and adapt for individual customers."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_EDITABLE_CUSTOMER_FIELDS_E001"
  ],
  "render_hints": {
    "assessmentDate": "[Assessment Date]"
  }
});
