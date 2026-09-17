export default Object.freeze({
  "requirement_id": "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS",
  "state_id": "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_S003",
  "key": "panel-gpio-button-and-switch-inputs",
  "title": "Panel GPIO Button and Switch Inputs",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "DIGITAL_IO",
    "CONNECTORS"
  ],
  "contexts": [
    "MAIN_BOARD",
    "PANEL_CONTROLS"
  ],
  "attributes": {
    "button_3": {
      "connector": "J_BTN3",
      "gpio": "GPIO6",
      "mounting": "panel"
    },
    "button_4": {
      "connector": "J_BTN4",
      "gpio": "GPIO7",
      "mounting": "panel"
    },
    "slide_switch": {
      "connector": "J_SW",
      "gpio": "GPIO8",
      "mounting": "panel"
    },
    "panel_control_board_interface": "off-board controls attached through connectors"
  },
  "ambiguity": {
    "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E003": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The schematic pull-downs conflict with the controls shorting their GPIOs to ground, leaving the required biasing and connector wiring unresolved.",
      "source_event_id": "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E003"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E001",
    "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E002",
    "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E003"
  ],
  "render_hints": {
    "panelInputCount": 3
  }
});
