export default Object.freeze({
  "requirement_id": "REQ_AXP2101_POWER_MANAGEMENT",
  "state_id": "REQ_AXP2101_POWER_MANAGEMENT_S001",
  "key": "axp2101-power-management",
  "title": "AXP2101 Power Management",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "BATTERY",
    "PMIC"
  ],
  "contexts": [
    "NORMAL_OPERATION",
    "BATTERY_OPERATION"
  ],
  "attributes": {
    "power_management_ic": "AXP2101",
    "normal_operation_power_source": "AXP2101",
    "required_system_rails": [
      "3.3V",
      "5V"
    ],
    "battery_power_path": "The battery supplies the AXP2101, which powers the system during normal operation."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_AXP2101_POWER_MANAGEMENT_E001"
  ],
  "render_hints": {}
});
