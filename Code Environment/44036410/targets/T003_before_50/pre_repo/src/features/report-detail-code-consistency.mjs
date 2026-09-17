export default Object.freeze({
  "requirement_id": "REQ_REPORT_CODE_CONSISTENCY",
  "state_id": "REQ_REPORT_CODE_CONSISTENCY_S002",
  "key": "report-detail-code-consistency",
  "title": "Report-Detail Code Consistency",
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
    "rr01_report_detail_identifier": "RR-01"
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The client reports that certain report sections may contain PR-01 rather than the required RR-01 identifier.",
    "source_event_id": "REQ_REPORT_CODE_CONSISTENCY_E002"
  },
  "supporting_event_ids": [
    "REQ_REPORT_CODE_CONSISTENCY_E001",
    "REQ_REPORT_CODE_CONSISTENCY_E002"
  ],
  "render_hints": {
    "bodyCode": "PR-01"
  }
});
