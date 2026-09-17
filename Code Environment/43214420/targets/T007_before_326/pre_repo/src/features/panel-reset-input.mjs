export default Object.freeze({
  "requirement_id": "REQ_PANEL_RESET_INPUT",
  "state_id": "REQ_PANEL_RESET_INPUT_S003",
  "key": "panel-reset-input",
  "title": "Panel Reset Input",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "CONNECTORS",
    "DIGITAL_IO"
  ],
  "contexts": [
    "MAIN_BOARD",
    "PANEL_CONTROLS",
    "RESET_INPUT"
  ],
  "attributes": {
    "interface_type": "JST connector for reset",
    "control_type": "reset button",
    "connector_designator": "J_RESET",
    "control_location": "panel-mounted",
    "electrical_action": "connect EN to GND"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PANEL_RESET_INPUT_E001",
    "REQ_PANEL_RESET_INPUT_E002",
    "REQ_PANEL_RESET_INPUT_E003"
  ],
  "render_hints": {}
});
