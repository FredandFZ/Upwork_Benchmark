export default Object.freeze({
  "requirement_id": "REQ_INTERNAL_HEADER_CODE_CONSISTENCY",
  "state_id": "REQ_INTERNAL_HEADER_CODE_CONSISTENCY_S001",
  "key": "internal-header-code-consistency",
  "title": "Internal-Header Code Consistency",
  "family": "REPORT_VARIANTS",
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_TEMPLATE"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "RR01"
  ],
  "attributes": {
    "rr01_internal_header_code": "RR-01"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_INTERNAL_HEADER_CODE_CONSISTENCY_E001"
  ],
  "render_hints": {
    "headerCode": "RR-01"
  }
});
