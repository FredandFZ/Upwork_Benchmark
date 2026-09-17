export default Object.freeze({
  "requirement_id": "REQ_DUAL_RAIL_CURRENT_MONITORING",
  "state_id": "REQ_DUAL_RAIL_CURRENT_MONITORING_S003",
  "key": "3-3v-and-5v-current-monitoring",
  "title": "3.3V and 5V Current Monitoring",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "SENSING",
    "I2C"
  ],
  "contexts": [
    "THREE_VOLT_THREE_RAIL",
    "FIVE_VOLT_RAIL"
  ],
  "attributes": {
    "monitored_rails": [
      "3.3V",
      "5V"
    ],
    "spare_monitor_channels": 1
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_DUAL_RAIL_CURRENT_MONITORING_E001",
    "REQ_DUAL_RAIL_CURRENT_MONITORING_E003"
  ],
  "render_hints": {}
});
