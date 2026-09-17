export default Object.freeze({
  "requirement_id": "REQ_BATTERY_CONNECTOR_INTERFACE",
  "state_id": "REQ_BATTERY_CONNECTOR_INTERFACE_S003",
  "key": "battery-connector-interface",
  "title": "Battery Connector Interface",
  "family": "POWER_AND_BATTERY_SYSTEM",
  "lifecycle": "ACTIVE",
  "components": [
    "BATTERY",
    "CONNECTORS"
  ],
  "contexts": [
    "POWER_BOARD"
  ],
  "attributes": {
    "ntc_contact_required": true,
    "battery_connection_access": "Battery must remain pluggable in the mounted orientation.",
    "battery_jst_location": "beside the board JST",
    "battery_jst_orientation": "L-shaped"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_BATTERY_CONNECTOR_INTERFACE_E001",
    "REQ_BATTERY_CONNECTOR_INTERFACE_E002",
    "REQ_BATTERY_CONNECTOR_INTERFACE_E003"
  ],
  "render_hints": {
    "batteryNtcContact": true,
    "batteryConnectorOrientation": "L-shaped"
  }
});
