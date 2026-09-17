export default Object.freeze({
  "requirement_id": "REQ_AXP_VRTC_HANDLING",
  "state_id": "REQ_AXP_VRTC_HANDLING_S004",
  "key": "axp2101-vrtc-handling",
  "title": "AXP2101 VRTC Handling",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "PMIC"
  ],
  "contexts": [
    "V1_BOARD",
    "NO_EXTERNAL_RTC"
  ],
  "attributes": {
    "vrtc_connection": "left_unconnected",
    "external_rtc_present": false
  },
  "ambiguity": {
    "REQ_AXP_VRTC_HANDLING_E004": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The freelancer reports adding an output from VRTC despite the client's instruction to leave VRTC unconnected for v1, leaving the intended VRTC connection unresolved.",
      "source_event_id": "REQ_AXP_VRTC_HANDLING_E004"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_AXP_VRTC_HANDLING_E002",
    "REQ_AXP_VRTC_HANDLING_E003",
    "REQ_AXP_VRTC_HANDLING_E004"
  ],
  "render_hints": {
    "vrtcHandling": "left_unconnected"
  }
});
