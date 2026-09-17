export default Object.freeze({
  "requirement_id": "REQ_CHARGE_STATUS_OUTPUT",
  "state_id": "REQ_CHARGE_STATUS_OUTPUT_S001",
  "key": "battery-charge-status-output",
  "title": "Battery Charge Status Output",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "LED"
  ],
  "contexts": [
    "CHARGE_STATUS",
    "MAIN_BOARD"
  ],
  "attributes": {
    "separate_charge_led_required": false,
    "charge_status_indication_path": "SK6812 addressable LED chain on GPIO13 on the main board"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_CHARGE_STATUS_OUTPUT_E001"
  ],
  "render_hints": {}
});
