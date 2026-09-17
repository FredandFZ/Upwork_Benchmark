export default Object.freeze({
  "requirement_id": "REQ_ESP32_DECOUPLING_LAYOUT",
  "state_id": "REQ_ESP32_DECOUPLING_LAYOUT_S004",
  "key": "esp32-decoupling-layout",
  "title": "ESP32 Decoupling Layout",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "MCU",
    "PCB_LAYOUT"
  ],
  "contexts": [
    "ESP32_POWER"
  ],
  "attributes": {
    "local_decoupling_capacitance": "0.1 µF",
    "bulk_decoupling_capacitance": "10 µF",
    "bulk_decoupling_placement": "may remain at its current location",
    "local_decoupling_placement": "retain the existing placement roughly 5–6 mm from the module's 3V3 pin"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_ESP32_DECOUPLING_LAYOUT_E001",
    "REQ_ESP32_DECOUPLING_LAYOUT_E003",
    "REQ_ESP32_DECOUPLING_LAYOUT_E004"
  ],
  "render_hints": {}
});
