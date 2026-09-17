export default Object.freeze({
  "requirement_id": "REQ_PCB_ORDER_CONFIGURATION",
  "state_id": "REQ_PCB_ORDER_CONFIGURATION_S003",
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
    "configuration_method": "add the board orders to the client's JLCPCB account through the email invitation"
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "The freelancer reports that attempting to access the client's JLCPCB account through the invitation produces an error.",
    "source_event_id": "REQ_PCB_ORDER_CONFIGURATION_E003"
  },
  "supporting_event_ids": [
    "REQ_PCB_ORDER_CONFIGURATION_E001",
    "REQ_PCB_ORDER_CONFIGURATION_E002",
    "REQ_PCB_ORDER_CONFIGURATION_E003"
  ],
  "render_hints": {}
});
