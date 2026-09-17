export default Object.freeze({
  "requirement_id": "REQ_CONNECTOR_PIN_LABELS",
  "state_id": "REQ_CONNECTOR_PIN_LABELS_S001",
  "key": "connector-pin-labels",
  "title": "Connector Pin Labels",
  "family": "MANUFACTURING_AND_DELIVERABLES",
  "lifecycle": "ACTIVE",
  "components": [
    "SILKSCREEN",
    "CONNECTORS"
  ],
  "contexts": [
    "POWER_BOARD",
    "PCB_MARKINGS"
  ],
  "attributes": {
    "marking_target": "connector pins",
    "marking_location": "bottom of the board"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_CONNECTOR_PIN_LABELS_E001"
  ],
  "render_hints": {}
});
