export default Object.freeze({
  "requirement_id": "REQ_COMPONENT_SOURCEABILITY",
  "state_id": "REQ_COMPONENT_SOURCEABILITY_S002",
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
    "compatible_alternative_policy": "A selected connector is acceptable only if compatible alternatives exist in case it goes out of stock.",
    "availability_priority": "Avoid components that may not remain consistently available."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_COMPONENT_SOURCEABILITY_E001",
    "REQ_COMPONENT_SOURCEABILITY_E002"
  ],
  "render_hints": {}
});
