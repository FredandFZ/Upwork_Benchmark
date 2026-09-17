export default Object.freeze({
  "requirement_id": "REQ_ESP32_ANTENNA_CLEARANCE",
  "state_id": "REQ_ESP32_ANTENNA_CLEARANCE_S001",
  "key": "esp32-antenna-clearance",
  "title": "ESP32 Antenna Clearance",
  "family": "PCB_ARCHITECTURE_AND_LAYOUT",
  "lifecycle": "ACTIVE",
  "components": [
    "PCB_LAYOUT",
    "RF"
  ],
  "contexts": [
    "MAIN_BOARD",
    "WIFI"
  ],
  "attributes": {
    "antenna_placement": "at the PCB edge"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_ESP32_ANTENNA_CLEARANCE_E001"
  ],
  "render_hints": {}
});
