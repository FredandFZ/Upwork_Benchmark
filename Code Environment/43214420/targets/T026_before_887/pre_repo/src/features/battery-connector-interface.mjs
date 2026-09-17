export default Object.freeze({
  "requirement_id": "REQ_BATTERY_CONNECTOR_INTERFACE",
  "state_id": "REQ_BATTERY_CONNECTOR_INTERFACE_S007",
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
    "battery_jst_orientation": "L-shaped",
    "connector_family": "JST-PH",
    "connector_pitch": "2.0 mm",
    "pin_count": 3,
    "pin_functions": [
      "GND",
      "VCC",
      "NTC"
    ],
    "standard_battery_compatibility_required": true
  },
  "ambiguity": {
    "REQ_BATTERY_CONNECTOR_INTERFACE_E007": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The correct physical battery-connector pin order remains unresolved after a labeling error was reported.",
      "source_event_id": "REQ_BATTERY_CONNECTOR_INTERFACE_E007"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_BATTERY_CONNECTOR_INTERFACE_E001",
    "REQ_BATTERY_CONNECTOR_INTERFACE_E002",
    "REQ_BATTERY_CONNECTOR_INTERFACE_E003",
    "REQ_BATTERY_CONNECTOR_INTERFACE_E005",
    "REQ_BATTERY_CONNECTOR_INTERFACE_E006",
    "REQ_BATTERY_CONNECTOR_INTERFACE_E007"
  ],
  "render_hints": {
    "batteryNtcContact": true,
    "batteryConnectorOrientation": "L-shaped"
  }
});
