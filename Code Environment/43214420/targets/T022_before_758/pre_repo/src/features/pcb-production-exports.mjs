export default Object.freeze({
  "requirement_id": "REQ_PRODUCTION_EXPORTS",
  "state_id": "REQ_PRODUCTION_EXPORTS_S002",
  "key": "pcb-production-exports",
  "title": "PCB Production Exports",
  "family": "MANUFACTURING_AND_DELIVERABLES",
  "lifecycle": "ACTIVE",
  "components": [
    "PCB_FILES",
    "MANUFACTURING"
  ],
  "contexts": [
    "PCB_FABRICATION",
    "ALL_BOARD_VARIANTS"
  ],
  "attributes": {
    "required_export_files": [
      "gerber_zip",
      "npth_drill_files",
      "pth_drill_files",
      "pick_and_place_positions_csv"
    ]
  },
  "ambiguity": null,
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer reports that the zip file now contains all required production files.",
    "source_event_id": "REQ_PRODUCTION_EXPORTS_E002"
  },
  "supporting_event_ids": [
    "REQ_PRODUCTION_EXPORTS_E001",
    "REQ_PRODUCTION_EXPORTS_E002"
  ],
  "render_hints": {}
});
