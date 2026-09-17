export default Object.freeze({
  "requirement_id": "REQ_POWER_BOARD_MECHANICAL_FORM_FACTOR",
  "state_id": "REQ_POWER_BOARD_MECHANICAL_FORM_FACTOR_S004",
  "key": "power-board-mechanical-form-factor",
  "title": "Power Board Mechanical Form Factor",
  "family": "PCB_ARCHITECTURE_AND_LAYOUT",
  "lifecycle": "ACTIVE",
  "components": [
    "PCB_LAYOUT",
    "MECHANICAL"
  ],
  "contexts": [
    "POWER_BOARD",
    "ENCLOSURE_FIT"
  ],
  "attributes": {
    "board_orientation": "must fit vertically in the shown orientation",
    "edge_component_position": "[CLIENT_NAME_002] must protrude slightly from the shorter edge",
    "mounting_hole_count": 4,
    "mounting_hole_location": "corners",
    "size_constraint": "as compact as the components allow",
    "usb_c_location": "shorter edge",
    "mounting_hole_size": "M2.5",
    "preferred_aspect_ratio": "approximately 2:1",
    "battery_connection_access": "Battery must remain pluggable in the mounted orientation."
  },
  "ambiguity": null,
  "execution": null,
  "supporting_event_ids": [
    "REQ_POWER_BOARD_MECHANICAL_FORM_FACTOR_E001",
    "REQ_POWER_BOARD_MECHANICAL_FORM_FACTOR_E002",
    "REQ_POWER_BOARD_MECHANICAL_FORM_FACTOR_E003",
    "REQ_POWER_BOARD_MECHANICAL_FORM_FACTOR_E004"
  ],
  "render_hints": {
    "mountingHoleCount": 4
  }
});
