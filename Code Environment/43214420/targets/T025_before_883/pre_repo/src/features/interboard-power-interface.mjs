export default Object.freeze({
  "requirement_id": "REQ_INTERBOARD_POWER_INTERFACE",
  "state_id": "REQ_INTERBOARD_POWER_INTERFACE_S004",
  "key": "interboard-power-interface",
  "title": "Interboard Power Interface",
  "family": "DIGITAL_CONNECTIVITY",
  "lifecycle": "ACTIVE",
  "components": [
    "POWER",
    "CONNECTORS"
  ],
  "contexts": [
    "THREE_BOARD_VARIANT",
    "INTERBOARD_POWER"
  ],
  "attributes": {
    "power_interboard_connector_reference": "J_PWR_POWER",
    "power_interboard_connector_type": "JST-PH 2.0mm",
    "power_interboard_connector_pin_count": 4,
    "power_interboard_pin_order_rule": "Pin order may be selected for layout convenience, but the power-board and main-board connectors must match.",
    "interboard_power_topology": "Power board to main board to sensor board",
    "main_board_power_input_connector": "J_PWR_PWR",
    "main_to_sensor_power_output_connector": "J_SENSOR_PWR",
    "main_board_power_distribution": "The main board uses incoming power locally and forwards it to the sensor board.",
    "sensor_board_power_input_connector_type": "JST-PH 2.0mm",
    "sensor_board_power_input_connector_pin_count": 4,
    "sensor_board_power_input_pinout": [
      "5V",
      "GND",
      "3V3",
      "GND"
    ]
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_INTERBOARD_POWER_INTERFACE_E001",
    "REQ_INTERBOARD_POWER_INTERFACE_E002",
    "REQ_INTERBOARD_POWER_INTERFACE_E003",
    "REQ_INTERBOARD_POWER_INTERFACE_E004"
  ],
  "render_hints": {}
});
