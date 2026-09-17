export default Object.freeze({
  "requirement_id": "REQ_DCDC1_OUTPUT_REGULATION",
  "state_id": "REQ_DCDC1_OUTPUT_REGULATION_S002",
  "key": "dcdc1-output-regulation",
  "title": "DCDC1 Output Regulation",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "PMIC"
  ],
  "contexts": [
    "THREE_VOLT_THREE_RAIL",
    "NORMAL_OPERATION",
    "BATTERY_OPERATION"
  ],
  "attributes": {
    "dcdc1_nominal_output_voltage": "3.4V",
    "dcdc1_rated_output_current": "2A",
    "normal_operation_role": "main 3.3V power source whenever the power board is attached",
    "downstream_rail_target_voltage": "3.3V",
    "voltage_compensation_purpose": "offset the main-board Schottky OR-ing diode drop"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_DCDC1_OUTPUT_REGULATION_E001",
    "REQ_DCDC1_OUTPUT_REGULATION_E002"
  ],
  "render_hints": {}
});
