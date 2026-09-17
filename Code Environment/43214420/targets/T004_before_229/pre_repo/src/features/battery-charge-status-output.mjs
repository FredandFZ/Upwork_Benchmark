export default Object.freeze({
  "requirement_id": "REQ_CHARGE_STATUS_OUTPUT",
  "state_id": "REQ_CHARGE_STATUS_OUTPUT_S002",
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
  "ambiguity": {
    "REQ_CHARGE_STATUS_OUTPUT_E002": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "Whether R6 should also be marked DNP while the on-board D1 charge LED is unpopulated is unresolved.",
      "source_event_id": "REQ_CHARGE_STATUS_OUTPUT_E002"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_CHARGE_STATUS_OUTPUT_E001",
    "REQ_CHARGE_STATUS_OUTPUT_E002"
  ],
  "render_hints": {}
});
