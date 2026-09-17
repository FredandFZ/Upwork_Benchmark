export default Object.freeze({
  "requirement_id": "REQ_BATTERY_SAFETY_PROTECTION",
  "state_id": "REQ_BATTERY_SAFETY_PROTECTION_S003",
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
    "thermal_sensing_input": "NTC on J_BAT",
    "overcharge_protection": "AXP2101 cutoff at 4.2V",
    "overdischarge_protection": "AXP2101 configurable cutoff at approximately 3.0V",
    "thermal_protection_required": true
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_BATTERY_SAFETY_PROTECTION_E001",
    "REQ_BATTERY_SAFETY_PROTECTION_E002",
    "REQ_BATTERY_SAFETY_PROTECTION_E003"
  ],
  "render_hints": {
    "batteryProtectionSpecified": true,
    "overchargeCutoffSpecified": true
  }
});
