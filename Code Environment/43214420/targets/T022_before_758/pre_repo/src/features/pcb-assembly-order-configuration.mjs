export default Object.freeze({
  "requirement_id": "REQ_PCB_ORDER_CONFIGURATION",
  "state_id": "REQ_PCB_ORDER_CONFIGURATION_S008",
  "key": "pcb-assembly-order-configuration",
  "title": "PCB Assembly Order Configuration",
  "family": "MANUFACTURING_AND_DELIVERABLES",
  "lifecycle": "ACTIVE",
  "components": [
    "MANUFACTURING"
  ],
  "contexts": [
    "JLCPCB_ORDER",
    "PCB_ASSEMBLY"
  ],
  "attributes": {
    "order_setup": "add the completed board files to JLCPCB and check the resulting order configuration for issues",
    "configuration_method": "add the board orders to the client's JLCPCB account through the email invitation",
    "missing_part_handling": "place the missing parts in the JLCPCB cart",
    "sensor_board_addition_condition": "add the sensor-board order after the missing parts become available",
    "optional_main_board_connector_order_policy": "The order may proceed with the optional ESP32-adjacent connectors unassembled when unavailable; include them when inexpensive."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PCB_ORDER_CONFIGURATION_E001",
    "REQ_PCB_ORDER_CONFIGURATION_E002",
    "REQ_PCB_ORDER_CONFIGURATION_E004",
    "REQ_PCB_ORDER_CONFIGURATION_E006",
    "REQ_PCB_ORDER_CONFIGURATION_E008"
  ],
  "render_hints": {}
});
