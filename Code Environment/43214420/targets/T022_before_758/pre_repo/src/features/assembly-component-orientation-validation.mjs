export default Object.freeze({
  "requirement_id": "REQ_COMPONENT_ORIENTATION_VALIDATION",
  "state_id": "REQ_COMPONENT_ORIENTATION_VALIDATION_S002",
  "key": "assembly-component-orientation-validation",
  "title": "Assembly Component Orientation Validation",
  "family": "MANUFACTURING_AND_DELIVERABLES",
  "lifecycle": "ACTIVE",
  "components": [
    "MANUFACTURING",
    "PCB_ASSEMBLY"
  ],
  "contexts": [
    "JLCPCB_ORDER",
    "COMPONENT_PLACEMENT"
  ],
  "attributes": {
    "orientation_acceptance_condition": "Verify in JLCPCB that component orientations are correct."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_COMPONENT_ORIENTATION_VALIDATION_E002"
  ],
  "render_hints": {}
});
