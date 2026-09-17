export default Object.freeze({
  "requirement_id": "REQ_INTERBOARD_POWER_INTERFACE",
  "state_id": "REQ_INTERBOARD_POWER_INTERFACE_S002",
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
    "power_interboard_pin_order_rule": "Pin order may be selected for layout convenience, but the power-board and main-board connectors must match."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_INTERBOARD_POWER_INTERFACE_E001",
    "REQ_INTERBOARD_POWER_INTERFACE_E002"
  ],
  "render_hints": {}
});
