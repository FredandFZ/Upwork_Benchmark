export default Object.freeze({
  "requirement_id": "REQ_ESP32_FULL_PIN_BREAKOUT",
  "state_id": "REQ_ESP32_FULL_PIN_BREAKOUT_S001",
  "key": "esp32-full-pin-breakout",
  "title": "ESP32 Full Pin Breakout",
  "family": "PCB_ARCHITECTURE_AND_LAYOUT",
  "lifecycle": "ACTIVE",
  "components": [
    "PCB_LAYOUT",
    "MCU"
  ],
  "contexts": [
    "MAIN_BOARD",
    "DEVELOPMENT_ACCESS"
  ],
  "attributes": {
    "pin_coverage": "unused ESP32 pins",
    "breakout_hole_placement": "may be placed anywhere and need not surround the ESP32 module"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_ESP32_FULL_PIN_BREAKOUT_E001"
  ],
  "render_hints": {
    "fullPinBreakout": false,
    "throughHoleBreakout": false
  }
});
