export default Object.freeze({
  "requirement_id": "REQ_INTERBOARD_SIGNAL_INTERFACE",
  "state_id": "REQ_INTERBOARD_SIGNAL_INTERFACE_S002",
  "key": "interboard-signal-interface",
  "title": "Interboard Signal Interface",
  "family": "DIGITAL_CONNECTIVITY",
  "lifecycle": "ACTIVE",
  "components": [
    "CONNECTORS",
    "DIGITAL_IO"
  ],
  "contexts": [
    "THREE_BOARD_VARIANT",
    "INTERBOARD_SIGNALS"
  ],
  "attributes": {
    "connector_selection": "separate power and signal connectors",
    "selection_reason": "compact form factor",
    "power_to_main_signal_connector": {
      "reference": "J_PWR_SIGNAL",
      "type": "JST-[FREELANCER_NAME_002]",
      "pitch": "1.25mm",
      "pin_count": 7
    },
    "power_to_main_signal_pinout": {
      "1": "SDA0",
      "2": "SCL0",
      "3": "IRQ",
      "4": "PWRON",
      "5": "D+",
      "6": "D-",
      "7": "5V_EN"
    }
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_INTERBOARD_SIGNAL_INTERFACE_E001",
    "REQ_INTERBOARD_SIGNAL_INTERFACE_E002"
  ],
  "render_hints": {}
});
