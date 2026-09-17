export default Object.freeze({
  "requirement_id": "REQ_TOUCH_INPUT_INTERFACES",
  "state_id": "REQ_TOUCH_INPUT_INTERFACES_S001",
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
    ]
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_TOUCH_INPUT_INTERFACES_E001"
  ],
  "render_hints": {
    "touchInputCount": 2,
    "inputBiasSpecified": false
  }
});
