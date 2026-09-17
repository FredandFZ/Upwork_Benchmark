export default Object.freeze({
  "requirement_id": "REQ_BOM_ASSEMBLY_READINESS",
  "state_id": "REQ_BOM_ASSEMBLY_READINESS_S006",
  "key": "assembly-ready-bom",
  "title": "Assembly-Ready BOM",
  "family": "MANUFACTURING_AND_DELIVERABLES",
  "lifecycle": "ACTIVE",
  "components": [
    "BOM",
    "MANUFACTURING"
  ],
  "contexts": [
    "PCB_ASSEMBLY",
    "POWER_BOARD"
  ],
  "attributes": {
    "jlcpcb_assembly_part_numbers_required": true
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The listed LED part number resolves to SK6805-EC20 rather than the specified SK6812 Mini-E, and the correct LCSC number remains unidentified.",
    "source_event_id": "REQ_BOM_ASSEMBLY_READINESS_E006"
  },
  "supporting_event_ids": [
    "REQ_BOM_ASSEMBLY_READINESS_E001",
    "REQ_BOM_ASSEMBLY_READINESS_E005",
    "REQ_BOM_ASSEMBLY_READINESS_E006"
  ],
  "render_hints": {
    "bomStatus": "failed"
  }
});
