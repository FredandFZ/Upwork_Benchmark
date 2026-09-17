export default Object.freeze({
  "requirement_id": "REQ_POWER_NET_CURRENT_CAPACITY",
  "state_id": "REQ_POWER_NET_CURRENT_CAPACITY_S002",
  "key": "power-net-current-capacity",
  "title": "Power Net Current Capacity",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "PCB_LAYOUT"
  ],
  "contexts": [
    "HIGH_CURRENT_ROUTING",
    "VBUS",
    "BATTERY_POWER"
  ],
  "attributes": {
    "minimum_power_stub_width": "≥1 mm",
    "minimum_width_nets": [
      "VBUS",
      "+5V",
      "BAT-"
    ]
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "Design review found several VBUS, +5V, and BAT- power stubs only 0.2–0.6 mm wide despite the specified minimum width of 1 mm.",
    "source_event_id": "REQ_POWER_NET_CURRENT_CAPACITY_E002"
  },
  "supporting_event_ids": [
    "REQ_POWER_NET_CURRENT_CAPACITY_E001",
    "REQ_POWER_NET_CURRENT_CAPACITY_E002"
  ],
  "render_hints": {}
});
