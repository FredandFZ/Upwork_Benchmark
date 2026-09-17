export default Object.freeze({
  "requirement_id": "REQ_ESP32_FULL_PIN_BREAKOUT",
  "state_id": "REQ_ESP32_FULL_PIN_BREAKOUT_S007",
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
  "ambiguity": {
    "REQ_ESP32_FULL_PIN_BREAKOUT_E007": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The current PDF specifies a 2.54 mm ESP32 breakout pitch, conflicting with the reported 1.27 mm pitch used on the main board.",
      "source_event_id": "REQ_ESP32_FULL_PIN_BREAKOUT_E007"
    }
  },
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer confirms that the main-board ESP32 breakout uses 1.27 mm pin headers.",
    "source_event_id": "REQ_ESP32_FULL_PIN_BREAKOUT_E006"
  },
  "supporting_event_ids": [
    "REQ_ESP32_FULL_PIN_BREAKOUT_E001",
    "REQ_ESP32_FULL_PIN_BREAKOUT_E002",
    "REQ_ESP32_FULL_PIN_BREAKOUT_E005",
    "REQ_ESP32_FULL_PIN_BREAKOUT_E006",
    "REQ_ESP32_FULL_PIN_BREAKOUT_E007"
  ],
  "render_hints": {
    "fullPinBreakout": true,
    "throughHoleBreakout": true
  }
});
