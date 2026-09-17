export default Object.freeze({
  "requirement_id": "REQ_PCB_ARCHITECTURE_VARIANTS",
  "state_id": "REQ_PCB_ARCHITECTURE_VARIANTS_S001",
  "key": "pcb-architecture-variants",
  "title": "PCB Architecture Variants",
  "family": "PCB_ARCHITECTURE_AND_LAYOUT",
  "lifecycle": "ACTIVE",
  "components": [
    "PCB_LAYOUT",
    "SYSTEM_ARCHITECTURE"
  ],
  "contexts": [
    "THREE_BOARD_VARIANT"
  ],
  "attributes": {
    "separate_board_architecture": "three-board design"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PCB_ARCHITECTURE_VARIANTS_E001"
  ],
  "render_hints": {
    "projectTitle": "Embedded Hardware Platform",
    "boardVariant": "three-board design",
    "boardCount": 3
  }
});
