export default Object.freeze({
  "requirement_id": "REQ_TOUCH_INPUT_INTERFACES",
  "state_id": "REQ_TOUCH_INPUT_INTERFACES_S004",
  "key": "capacitive-touch-input-interfaces",
  "title": "Capacitive Touch Input Interfaces",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "DIGITAL_IO",
    "CONNECTORS"
  ],
  "contexts": [
    "CAPACITIVE_TOUCH"
  ],
  "attributes": {
    "touch_inputs": [
      {
        "connector": "J_TOUCH",
        "sensor": "TTP223",
        "gpio": "GPIO11"
      },
      {
        "connector": "J_TOUCH2",
        "sensor": "TTP223",
        "gpio": "GPIO14"
      }
    ],
    "output_type": "push-pull",
    "active_level": "HIGH",
    "bias_resistors": {
      "R20": "10 k pull-down to GND",
      "R25": "10 k pull-down to GND"
    },
    "disconnected_state": "LOW"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_TOUCH_INPUT_INTERFACES_E001",
    "REQ_TOUCH_INPUT_INTERFACES_E003",
    "REQ_TOUCH_INPUT_INTERFACES_E004"
  ],
  "render_hints": {
    "touchInputCount": 2,
    "inputBiasSpecified": true
  }
});
