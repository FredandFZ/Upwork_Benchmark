export default Object.freeze({
  "requirement_id": "REQ_BATTERY_CONNECTOR_INTERFACE",
  "state_id": "REQ_BATTERY_CONNECTOR_INTERFACE_S002",
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
    "battery_connection_access": "Battery must remain pluggable in the mounted orientation."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_BATTERY_CONNECTOR_INTERFACE_E001",
    "REQ_BATTERY_CONNECTOR_INTERFACE_E002"
  ],
  "render_hints": {
    "batteryNtcContact": true
  }
});
