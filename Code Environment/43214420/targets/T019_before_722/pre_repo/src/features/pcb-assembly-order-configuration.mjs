export default Object.freeze({
  "requirement_id": "REQ_PCB_ORDER_CONFIGURATION",
  "state_id": "REQ_PCB_ORDER_CONFIGURATION_S007",
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
    "sensor_board_addition_condition": "add the sensor-board order after the missing parts become available"
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The client reports that proceeding through the JLCPCB main-board order still shows two missing components.",
    "source_event_id": "REQ_PCB_ORDER_CONFIGURATION_E007"
  },
  "supporting_event_ids": [
    "REQ_PCB_ORDER_CONFIGURATION_E001",
    "REQ_PCB_ORDER_CONFIGURATION_E002",
    "REQ_PCB_ORDER_CONFIGURATION_E004",
    "REQ_PCB_ORDER_CONFIGURATION_E006",
    "REQ_PCB_ORDER_CONFIGURATION_E007"
  ],
  "render_hints": {}
});
