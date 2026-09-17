export default Object.freeze({
  "requirement_id": "REQ_POWER_DECOUPLING_LAYOUT",
  "state_id": "REQ_POWER_DECOUPLING_LAYOUT_S001",
  "key": "power-converter-decoupling-layout",
  "title": "Power Converter Decoupling Layout",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "PCB_LAYOUT"
  ],
  "contexts": [
    "SWITCHING_POWER"
  ],
  "attributes": {
    "converter_capacitor_placement": "Place the AXP2101 decoupling capacitors and MT3608 output capacitors closer to their packages where layout constraints permit, using the tighter typical-reference placement as the goal."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_POWER_DECOUPLING_LAYOUT_E001"
  ],
  "render_hints": {}
});
