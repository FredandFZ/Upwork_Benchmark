export default Object.freeze({
  "requirement_id": "REQ_CHARGE_STATUS_OUTPUT",
  "state_id": "REQ_CHARGE_STATUS_OUTPUT_S003",
  "key": "battery-charge-status-output",
  "title": "Battery Charge Status Output",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "LED",
    "CONNECTORS"
  ],
  "contexts": [
    "CHARGE_STATUS",
    "MAIN_BOARD",
    "POWER_BOARD"
  ],
  "attributes": {
    "separate_charge_led_required": true,
    "charge_status_indication_path": "SK6812 addressable LED chain on GPIO13 on the main board",
    "charge_status_connector": "J_LED_CHG, 2-pin JST-[FREELANCER_NAME_002]",
    "charge_status_resistor_reference": "R6",
    "charge_status_resistor_value": "270Ω",
    "charge_status_resistor_population": "populated",
    "on_board_charge_led_reference": "D1",
    "on_board_charge_led_population": "DNP"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_CHARGE_STATUS_OUTPUT_E001",
    "REQ_CHARGE_STATUS_OUTPUT_E003"
  ],
  "render_hints": {}
});
