export default Object.freeze({
  "requirement_id": "REQ_SENSOR_BOARD_CONNECTOR_HUB",
  "state_id": "REQ_SENSOR_BOARD_CONNECTOR_HUB_S001",
  "key": "sensor-board-connector-hub",
  "title": "Sensor Board Connector Hub",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "CONNECTORS",
    "SENSOR_INTERFACE"
  ],
  "contexts": [
    "SENSOR_BOARD",
    "SENSOR_MODULES"
  ],
  "attributes": {
    "board_role": "connector hub for sensors"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_SENSOR_BOARD_CONNECTOR_HUB_E001"
  ],
  "render_hints": {}
});
