export default Object.freeze({
  "requirement_id": "REQ_POWER_NET_CURRENT_CAPACITY",
  "state_id": "REQ_POWER_NET_CURRENT_CAPACITY_S004",
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
    "high_current_nets": [
      "VBUS",
      "BAT−"
    ],
    "worst_case_current": "~1.5 A (1 A charging plus approximately 0.5 A system load)",
    "current_path_requirement": "Copper pours must remain continuous from the USB-C or battery connector through to the corresponding AXP2101 VBUS or BAT pin.",
    "series_bottleneck_prohibition": "No thin trace, including a 0.2 mm trace, may act as a series bottleneck.",
    "stitching_requirement": "Provide sufficient interlayer stitching on the high-current nets, typically at least 3 vias for approximately 1.5 A."
  },
  "ambiguity": null,
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer reports that the implemented battery traces can carry 2.5 A without a problem.",
    "source_event_id": "REQ_POWER_NET_CURRENT_CAPACITY_E004"
  },
  "supporting_event_ids": [
    "REQ_POWER_NET_CURRENT_CAPACITY_E001",
    "REQ_POWER_NET_CURRENT_CAPACITY_E003",
    "REQ_POWER_NET_CURRENT_CAPACITY_E004"
  ],
  "render_hints": {}
});
