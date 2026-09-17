export default Object.freeze({
  "requirement_id": "REQ_SEPARATE_BOARD_CONNECTOR_LAYOUT",
  "state_id": "REQ_SEPARATE_BOARD_CONNECTOR_LAYOUT_S003",
  "key": "separate-board-connector-placement",
  "title": "Separate-Board Connector Placement",
  "family": "PCB_ARCHITECTURE_AND_LAYOUT",
  "lifecycle": "ACTIVE",
  "components": [
    "PCB_LAYOUT",
    "CONNECTORS"
  ],
  "contexts": [
    "MAIN_BOARD",
    "SENSOR_BOARD",
    "THREE_BOARD_VARIANT"
  ],
  "attributes": {
    "board_mounting_orientation": "main and sensor boards mounted vertically with their long edges at the top",
    "high_pin_count_connector_placement": "along the long top edge of both boards, with none on the sides or bottom",
    "sensor_interboard_connector_alignment": "J_SENSOR_PWR and J_SENSOR_SIG aligned at the same relative top-edge positions on the main and sensor boards",
    "interboard_cable_routing": "short, straight cable runs between aligned connectors",
    "bottom_side_placement": "minimize placement on the downward-facing, difficult-to-reach bottom side",
    "small_connector_placement": "top or side placement is allowed where it makes cables easier to connect"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_SEPARATE_BOARD_CONNECTOR_LAYOUT_E001",
    "REQ_SEPARATE_BOARD_CONNECTOR_LAYOUT_E002",
    "REQ_SEPARATE_BOARD_CONNECTOR_LAYOUT_E003"
  ],
  "render_hints": {
    "connectorTopAligned": true,
    "lowerConnectorsUpward": false
  }
});
