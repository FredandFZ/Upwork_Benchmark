export default Object.freeze({
  "requirement_id": "REQ_PCB_ARCHITECTURE_VARIANTS",
  "state_id": "REQ_PCB_ARCHITECTURE_VARIANTS_S002",
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
    "separate_board_architecture": "three-board design",
    "main_board_role": "standard ESP32-S3 board",
    "sensor_board_role": "sensor connector board"
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PCB_ARCHITECTURE_VARIANTS_E001",
    "REQ_PCB_ARCHITECTURE_VARIANTS_E002"
  ],
  "render_hints": {
    "projectTitle": "Embedded Hardware Platform",
    "boardVariant": "three-board design | standard ESP32-S3 board | sensor connector board",
    "boardCount": 3
  }
});
