export default Object.freeze({
  "requirement_id": "REQ_LEAD_FREE_MANUFACTURING",
  "state_id": "REQ_LEAD_FREE_MANUFACTURING_S001",
  "key": "lead-free-manufacturing",
  "title": "Lead-Free Manufacturing",
  "family": "MANUFACTURING_AND_DELIVERABLES",
  "lifecycle": "ACTIVE",
  "components": [
    "MANUFACTURING"
  ],
  "contexts": [
    "PCB_ASSEMBLY",
    "ALL_BOARD_VARIANTS"
  ],
  "attributes": {
    "lead_free_manufacturing": true
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_LEAD_FREE_MANUFACTURING_E001"
  ],
  "render_hints": {}
});
