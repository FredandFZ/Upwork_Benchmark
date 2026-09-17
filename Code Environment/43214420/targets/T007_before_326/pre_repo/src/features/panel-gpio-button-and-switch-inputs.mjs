export default Object.freeze({
  "requirement_id": "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS",
  "state_id": "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_S001",
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
    }
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E001"
  ],
  "render_hints": {
    "panelInputCount": 3
  }
});
