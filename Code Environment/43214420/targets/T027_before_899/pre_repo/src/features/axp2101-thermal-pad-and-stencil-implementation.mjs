export default Object.freeze({
  "requirement_id": "REQ_AXP_THERMAL_PAD_IMPLEMENTATION",
  "state_id": "REQ_AXP_THERMAL_PAD_IMPLEMENTATION_S002",
  "key": "axp2101-thermal-pad-and-stencil-implementation",
  "title": "AXP2101 Thermal Pad and Stencil Implementation",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "PCB_LAYOUT"
  ],
  "contexts": [
    "AXP2101_THERMAL_MANAGEMENT"
  ],
  "attributes": {
    "thermal_pad_function": "transfer heat from the AXP2101 through its underside pad for cooling"
  },
  "ambiguity": null,
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer reports that the AXP2101 underside-pad thermal management is handled in the board design.",
    "source_event_id": "REQ_AXP_THERMAL_PAD_IMPLEMENTATION_E002"
  },
  "supporting_event_ids": [
    "REQ_AXP_THERMAL_PAD_IMPLEMENTATION_E001",
    "REQ_AXP_THERMAL_PAD_IMPLEMENTATION_E002"
  ],
  "render_hints": {}
});
