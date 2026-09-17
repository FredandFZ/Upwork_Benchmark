export default Object.freeze({
  "requirement_id": "REQ_TOUCH_INPUT_INTERFACES",
  "state_id": "REQ_TOUCH_INPUT_INTERFACES_S002",
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
  "ambiguity": {
    "REQ_TOUCH_INPUT_INTERFACES_E002": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The freelancer raises a material uncertainty about whether the touch-input circuitry involving R20/R25 is correct.",
      "source_event_id": "REQ_TOUCH_INPUT_INTERFACES_E002"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_TOUCH_INPUT_INTERFACES_E001",
    "REQ_TOUCH_INPUT_INTERFACES_E002"
  ],
  "render_hints": {
    "touchInputCount": 2,
    "inputBiasSpecified": false
  }
});
