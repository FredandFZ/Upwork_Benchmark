export default Object.freeze({
  "requirement_id": "REQ_ESP32_FULL_PIN_BREAKOUT",
  "state_id": "REQ_ESP32_FULL_PIN_BREAKOUT_S002",
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
    "pin_coverage": "every ESP32-S3 module pin",
    "breakout_hole_placement": "may be placed anywhere and need not surround the ESP32 module",
    "breakout_format": "through-hole",
    "platform_purpose": "reusable general ESP32-S3 base platform"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_ESP32_FULL_PIN_BREAKOUT_E001",
    "REQ_ESP32_FULL_PIN_BREAKOUT_E002"
  ],
  "render_hints": {
    "fullPinBreakout": true,
    "throughHoleBreakout": true
  }
});
