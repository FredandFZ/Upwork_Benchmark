export default Object.freeze({
  "requirement_id": "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS",
  "state_id": "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_S006",
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
    "panel_control_board_interface": "off-board controls attached through connectors",
    "input_bias": {
      "R16": "pull-up to 3V3",
      "R17": "pull-up to 3V3",
      "R18": "pull-up to 3V3"
    },
    "input_logic": "active LOW",
    "connector_pin_1": "GND",
    "pressed_behavior": "short GPIO to GND"
  },
  "ambiguity": null,
  "execution": {
    "status": "CLAIMED_WORKING",
    "observed_behavior": "Freelancer reports that R16, R17, and R18 were reconnected to 3.3V as required for the panel button and switch pull-ups.",
    "source_event_id": "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E006"
  },
  "supporting_event_ids": [
    "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E001",
    "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E002",
    "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E004",
    "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E005",
    "REQ_PANEL_GPIO_BUTTON_SWITCH_INPUTS_E006"
  ],
  "render_hints": {
    "panelInputCount": 3,
    "inputBiasSpecified": true
  }
});
