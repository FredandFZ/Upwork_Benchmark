export default Object.freeze({
  "requirement_id": "REQ_INTERNAL_PAGE_HEADER",
  "state_id": "REQ_INTERNAL_PAGE_HEADER_S002",
  "key": "internal-page-header",
  "title": "Internal-Page Header",
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
    "page_coverage": "every page",
    "header_style": "clean and consistent"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_INTERNAL_PAGE_HEADER_E001",
    "REQ_INTERNAL_PAGE_HEADER_E002"
  ],
  "render_hints": {
    "headerEnabled": true
  }
});
