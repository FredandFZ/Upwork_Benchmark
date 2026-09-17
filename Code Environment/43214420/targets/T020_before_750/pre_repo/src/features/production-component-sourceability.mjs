export default Object.freeze({
  "requirement_id": "REQ_COMPONENT_SOURCEABILITY",
  "state_id": "REQ_COMPONENT_SOURCEABILITY_S009",
  "key": "production-component-sourceability",
  "title": "Production Component Sourceability",
  "family": "MANUFACTURING_AND_DELIVERABLES",
  "lifecycle": "ACTIVE",
  "components": [
    "BOM",
    "MANUFACTURING"
  ],
  "contexts": [
    "COMPONENT_SOURCING",
    "USB_CONNECTOR"
  ],
  "attributes": {
    "component_selection_rule": "Use a standard connector that can be sourced easily.",
    "sourceability_check": "Availability on AliExpress is an acceptable sourceability test.",
    "availability_priority": "Avoid components that may not remain consistently available.",
    "high_moq_connector_fallback": "If no suitable alternative exists, purchasing the connector at the required minimum quantity is acceptable.",
    "optional_main_board_connector_policy": "The optional ESP32-adjacent connectors may be left unassembled when unavailable; include them when inexpensive."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_COMPONENT_SOURCEABILITY_E001",
    "REQ_COMPONENT_SOURCEABILITY_E002",
    "REQ_COMPONENT_SOURCEABILITY_E006",
    "REQ_COMPONENT_SOURCEABILITY_E009"
  ],
  "render_hints": {}
});
