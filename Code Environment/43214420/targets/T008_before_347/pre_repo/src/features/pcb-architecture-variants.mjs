export default Object.freeze({
  "requirement_id": "REQ_PCB_ARCHITECTURE_VARIANTS",
  "state_id": "REQ_PCB_ARCHITECTURE_VARIANTS_S003",
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
    "main_board_role": "ESP32-S3 processing, 3.3V current monitoring, USB programming and standalone regulation, and system connectors",
    "sensor_board_role": "sensor connector board",
    "main_board_exclusions": [
      "sensors",
      "power management"
    ]
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_PCB_ARCHITECTURE_VARIANTS_E001",
    "REQ_PCB_ARCHITECTURE_VARIANTS_E002",
    "REQ_PCB_ARCHITECTURE_VARIANTS_E003"
  ],
  "render_hints": {
    "projectTitle": "Embedded Hardware Platform",
    "boardVariant": "three-board design | ESP32-S3 processing, 3.3V current monitoring, USB programming and standalone regulation, and system",
    "boardCount": 3
  }
});
