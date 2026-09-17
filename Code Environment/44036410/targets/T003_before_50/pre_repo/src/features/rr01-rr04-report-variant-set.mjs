export default Object.freeze({
  "requirement_id": "REQ_REPORT_VARIANT_SET",
  "state_id": "REQ_REPORT_VARIANT_SET_S001",
  "key": "rr01-rr04-report-variant-set",
  "title": "RR01–RR04 Report Variant Set",
  "family": "REPORT_VARIANTS",
  "lifecycle": "ACTIVE",
  "components": [
    "DOCUMENT_TEMPLATE"
  ],
  "contexts": [
    "VEHICLE_SECURITY_REPORT",
    "RR01",
    "RR02",
    "RR03",
    "RR04"
  ],
  "attributes": {
    "variant_count": 4,
    "variant_ids": [
      "RR01",
      "RR02",
      "RR03",
      "RR04"
    ],
    "selection_basis": "customer score/risk level"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_REPORT_VARIANT_SET_E001"
  ],
  "render_hints": {}
});
