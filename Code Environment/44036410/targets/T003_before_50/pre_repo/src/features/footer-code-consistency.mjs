export default Object.freeze({
  "requirement_id": "REQ_FOOTER_CODE_CONSISTENCY",
  "state_id": "REQ_FOOTER_CODE_CONSISTENCY_S001",
  "key": "footer-code-consistency",
  "title": "Footer Code Consistency",
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
    "rr01_footer_code": "RR-01"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_FOOTER_CODE_CONSISTENCY_E001"
  ],
  "render_hints": {
    "footerCode": "RR-01"
  }
});
