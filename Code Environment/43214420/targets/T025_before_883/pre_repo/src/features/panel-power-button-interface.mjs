export default Object.freeze({
  "requirement_id": "REQ_PANEL_POWER_BUTTON",
  "state_id": "REQ_PANEL_POWER_BUTTON_S002",
  "key": "panel-power-button-interface",
  "title": "Panel Power Button Interface",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "CONNECTORS",
    "UI_UX"
  ],
  "contexts": [
    "POWER_CONTROL",
    "ENCLOSURE_PANEL",
    "MAIN_BOARD"
  ],
  "attributes": {
    "connector_designator": "J_PWR_BTN",
    "connector_type": "2-pin JST-[FREELANCER_NAME_002]",
    "board_location": "main board",
    "button_mounting": "panel-mounted",
    "button_type": "momentary",
    "connected_signal": "AXP2101 PWRON",
    "switch_behavior": "Press to switch on and press again to switch off.",
    "signal_connection": "Tap PWRON from J_PWR_SIG pin 4."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PANEL_POWER_BUTTON_E001",
    "REQ_PANEL_POWER_BUTTON_E002"
  ],
  "render_hints": {}
});
