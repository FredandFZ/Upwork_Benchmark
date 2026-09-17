export default Object.freeze({
  "requirement_id": "REQ_BOM_ASSEMBLY_READINESS",
  "state_id": "REQ_BOM_ASSEMBLY_READINESS_S007",
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
    "jlcpcb_assembly_part_numbers_required": true,
    "led_lcsc_part_number": "C5149201",
    "led_model": "SK6812MINI-E",
    "led_manufacturer": "OPSCO Optoelectronics",
    "led_package": "3228",
    "led_package_dimensions": "3.2×2.8mm",
    "led_mounting": "4-pad SMD",
    "led_color_channels": "RGBW"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_BOM_ASSEMBLY_READINESS_E001",
    "REQ_BOM_ASSEMBLY_READINESS_E005",
    "REQ_BOM_ASSEMBLY_READINESS_E007"
  ],
  "render_hints": {
    "bomStatus": "specified"
  }
});
