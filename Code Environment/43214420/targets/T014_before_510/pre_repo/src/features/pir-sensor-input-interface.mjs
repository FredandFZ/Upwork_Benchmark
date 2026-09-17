export default Object.freeze({
  "requirement_id": "REQ_PIR_INPUT_INTERFACE",
  "state_id": "REQ_PIR_INPUT_INTERFACE_S001",
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
    "pir_connector_provided": true
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PIR_INPUT_INTERFACE_E001"
  ],
  "render_hints": {
    "pirInputPresent": true
  }
});
