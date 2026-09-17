export default Object.freeze({
  "requirement_id": "REQ_AXP_VRTC_HANDLING",
  "state_id": "REQ_AXP_VRTC_HANDLING_S001",
  "key": "axp2101-vrtc-handling",
  "title": "AXP2101 VRTC Handling",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "OBSERVED",
  "components": [],
  "contexts": [],
  "attributes": {},
  "ambiguity": {
    "REQ_AXP_VRTC_HANDLING_E001": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "It is unresolved whether the unused VRTC pin should remain unconnected or require a capacitor to ground.",
      "source_event_id": "REQ_AXP_VRTC_HANDLING_E001"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_AXP_VRTC_HANDLING_E001"
  ],
  "render_hints": {
    "vrtcHandling": "specified"
  }
});
