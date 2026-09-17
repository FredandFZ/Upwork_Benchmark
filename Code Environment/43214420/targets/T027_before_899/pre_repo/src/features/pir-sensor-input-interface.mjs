export default Object.freeze({
  "requirement_id": "REQ_PIR_INPUT_INTERFACE",
  "state_id": "REQ_PIR_INPUT_INTERFACE_S002",
  "key": "pir-sensor-input-interface",
  "title": "PIR Sensor Input Interface",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "DIGITAL_IO",
    "CONNECTORS"
  ],
  "contexts": [
    "PIR_SENSOR"
  ],
  "attributes": {
    "pir_connector_provided": true,
    "sensor_model": "AM312",
    "output_driver": "push-pull",
    "active_level": "HIGH",
    "bias_configuration": "R19 10 kΩ pull-down to GND",
    "disconnected_state": "LOW"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PIR_INPUT_INTERFACE_E001",
    "REQ_PIR_INPUT_INTERFACE_E002"
  ],
  "render_hints": {
    "pirInputPresent": true,
    "inputBiasSpecified": true
  }
});
