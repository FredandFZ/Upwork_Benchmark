export default Object.freeze({
  "requirement_id": "REQ_INTERNAL_PAGE_HEADER",
  "state_id": "REQ_INTERNAL_PAGE_HEADER_S003",
  "key": "internal-page-header",
  "title": "Internal-Page Header",
  "family": "RUNNING_PAGE_ELEMENTS",
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_TEMPLATE"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "INTERNAL_PAGES",
    "RR01",
    "RR02",
    "RR03",
    "RR04"
  ],
  "attributes": {
    "page_coverage": "pages 2 onwards",
    "header_style": "subtle, understated, and space-efficient",
    "header_information": [
      "report_name",
      "report_code",
      "confidentiality_status"
    ]
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_INTERNAL_PAGE_HEADER_E001",
    "REQ_INTERNAL_PAGE_HEADER_E003"
  ],
  "render_hints": {
    "headerEnabled": true
  }
});
