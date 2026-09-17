export default Object.freeze({
  "requirement_id": "REQ_ESP32_ANTENNA_CLEARANCE",
  "state_id": "REQ_ESP32_ANTENNA_CLEARANCE_S003",
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
    "INTEGRATED_BOARD_VARIANT",
    "WIFI"
  ],
  "attributes": {
    "antenna_placement": "at the PCB edge",
    "antenna_direction": "away from the battery",
    "minimum_antenna_keepout": "≥3 mm"
  },
  "ambiguity": {
    "REQ_ESP32_ANTENNA_CLEARANCE_E003": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "It remains unresolved whether components may remain in the secondary recommended antenna clear area with reduced WiFi range or whether that area must be cleared.",
      "source_event_id": "REQ_ESP32_ANTENNA_CLEARANCE_E003"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_ESP32_ANTENNA_CLEARANCE_E001",
    "REQ_ESP32_ANTENNA_CLEARANCE_E002",
    "REQ_ESP32_ANTENNA_CLEARANCE_E003"
  ],
  "render_hints": {}
});
