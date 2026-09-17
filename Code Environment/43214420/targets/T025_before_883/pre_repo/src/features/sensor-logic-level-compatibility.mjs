export default Object.freeze({
  "requirement_id": "REQ_SENSOR_LOGIC_LEVEL_COMPATIBILITY",
  "state_id": "REQ_SENSOR_LOGIC_LEVEL_COMPATIBILITY_S001",
  "key": "sensor-logic-level-compatibility",
  "title": "Sensor Logic-Level Compatibility",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "OBSERVED",
  "components": [
    "SENSOR_INTERFACE",
    "DIGITAL_IO"
  ],
  "contexts": [
    "SENSOR_BOARD",
    "I2C",
    "UART"
  ],
  "attributes": {
    "current_sensors_require_level_shifting": false,
    "sensor_board_level_shifter_footprints": "omitted",
    "future_5v_logic_sensor_support": "external adapter board"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_SENSOR_LOGIC_LEVEL_COMPATIBILITY_E001"
  ],
  "render_hints": {}
});
