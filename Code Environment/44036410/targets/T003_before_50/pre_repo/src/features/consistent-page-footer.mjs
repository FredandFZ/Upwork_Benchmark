export default Object.freeze({
  "requirement_id": "REQ_PAGE_FOOTER",
  "state_id": "REQ_PAGE_FOOTER_S003",
  "key": "consistent-page-footer",
  "title": "Consistent Page Footer",
  "family": "RUNNING_PAGE_ELEMENTS",
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_TEMPLATE"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "ALL_PAGES",
    "RR01",
    "RR02",
    "RR03",
    "RR04"
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
  "execution": {
    "status": "VERIFIED_WORKING",
    "observed_behavior": "The client reports that the footer in the reviewed report design is working well.",
    "source_event_id": "REQ_PAGE_FOOTER_E003"
  },
  "supporting_event_ids": [
    "REQ_PAGE_FOOTER_E001",
    "REQ_PAGE_FOOTER_E002",
    "REQ_PAGE_FOOTER_E003"
  ],
  "render_hints": {
    "footerAllPages": true
  }
});
