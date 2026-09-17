export default Object.freeze({
  "requirement_id": "REQ_BATTERY_SAFETY_PROTECTION",
  "state_id": "REQ_BATTERY_SAFETY_PROTECTION_S001",
  "key": "battery-safety-protection",
  "title": "Battery Safety Protection",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "BATTERY",
    "PROTECTION"
  ],
  "contexts": [
    "POWER_BOARD"
  ],
  "attributes": {
    "battery_protection_required": true,
    "thermal_sensing_input": "third NTC terminal"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_BATTERY_SAFETY_PROTECTION_E001"
  ],
  "render_hints": {
    "batteryProtectionSpecified": true,
    "overchargeCutoffSpecified": false
  }
});
