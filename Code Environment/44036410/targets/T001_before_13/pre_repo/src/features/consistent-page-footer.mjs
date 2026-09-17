export default Object.freeze({
  "requirement_id": "REQ_PAGE_FOOTER",
  "state_id": "REQ_PAGE_FOOTER_S001",
  "key": "consistent-page-footer",
  "title": "Consistent Page Footer",
  "family": "RUNNING_PAGE_ELEMENTS",
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_TEMPLATE"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "ALL_PAGES"
  ],
  "attributes": {
    "footer_style": "clean and consistent",
    "page_coverage": "every page",
    "footer_information": [
      "report_name",
      "report_id",
      "vehicle_group",
      "confidential_or_restricted_status",
      "assessment_date",
      "page_number"
    ]
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PAGE_FOOTER_E001"
  ],
  "render_hints": {
    "footerAllPages": true
  }
});
