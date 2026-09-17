export default Object.freeze({
  "requirement_id": "REQ_INTEGRATED_SENSOR_CONNECTOR_MATRIX",
  "state_id": "REQ_INTEGRATED_SENSOR_CONNECTOR_MATRIX_S002",
  "key": "integrated-board-sensor-connector-matrix",
  "title": "Integrated Board Sensor Connector Matrix",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "OBSERVED",
  "components": [
    "CONNECTORS",
    "SENSOR_INTERFACE"
  ],
  "contexts": [
    "INTEGRATED_BOARD",
    "LIGHT_SENSOR"
  ],
  "attributes": {
    "light_sensor_i2c_connector": {
      "included": true,
      "interface": "I2C JST",
      "purpose": "light sensor for the backlight"
    },
    "previously_omitted_jst_connector": {
      "included": true,
      "quantity": 1,
      "connector_type": "JST [FREELANCER_NAME_002]"
    }
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_INTEGRATED_SENSOR_CONNECTOR_MATRIX_E001",
    "REQ_INTEGRATED_SENSOR_CONNECTOR_MATRIX_E002"
  ],
  "render_hints": {}
});
