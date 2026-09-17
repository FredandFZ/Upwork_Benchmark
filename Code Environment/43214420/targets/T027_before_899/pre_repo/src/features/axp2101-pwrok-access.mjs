export default Object.freeze({
  "requirement_id": "REQ_AXP_PWROK_ACCESS",
  "state_id": "REQ_AXP_PWROK_ACCESS_S001",
  "key": "axp2101-pwrok-access",
  "title": "AXP2101 PWROK Access",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "PMIC",
    "PCB_LAYOUT"
  ],
  "contexts": [
    "AXP2101_DEBUGGING"
  ],
  "attributes": {
    "pwrok_pin": 29,
    "pwrok_breakout": "small test pad or via",
    "intended_use": "debugging"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_AXP_PWROK_ACCESS_E001"
  ],
  "render_hints": {}
});
