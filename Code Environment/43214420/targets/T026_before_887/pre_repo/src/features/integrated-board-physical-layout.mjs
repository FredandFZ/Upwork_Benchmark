export default Object.freeze({
  "requirement_id": "REQ_INTEGRATED_BOARD_PHYSICAL_LAYOUT",
  "state_id": "REQ_INTEGRATED_BOARD_PHYSICAL_LAYOUT_S005",
  "key": "integrated-board-physical-layout",
  "title": "Integrated Board Physical Layout",
  "family": "PCB_ARCHITECTURE_AND_LAYOUT",
  "lifecycle": "ACTIVE",
  "components": [
    "PCB_LAYOUT",
    "MECHANICAL",
    "CONNECTORS"
  ],
  "contexts": [
    "INTEGRATED_BOARD_VARIANT",
    "ENCLOSURE_FIT"
  ],
  "attributes": {
    "board_orientation_rule": "Use whichever board orientation produces the cleanest connector layout, with the enclosure adapted to the board.",
    "battery_connector_location": "Place J_BAT on a short edge alongside the battery.",
    "usb_c_location": "Place USB-C on a short, user-facing edge.",
    "display_connector_grouping": "Keep J_DISP_SPI, J_DISP_I2C, and J_DISP_LED together on the edge nearest the display-flex route.",
    "general_connector_placement": "Connectors may be positioned along the proposed three board sides, with placement otherwise flexible subject to the specified battery, USB-C, and display-connector constraints."
  },
  "ambiguity": null,
  "execution": {
    "status": "VERIFIED_WORKING",
    "observed_behavior": "The client visually approved the revised integrated-board layout after the battery-connector clearance problem was raised.",
    "source_event_id": "REQ_INTEGRATED_BOARD_PHYSICAL_LAYOUT_E005"
  },
  "supporting_event_ids": [
    "REQ_INTEGRATED_BOARD_PHYSICAL_LAYOUT_E001",
    "REQ_INTEGRATED_BOARD_PHYSICAL_LAYOUT_E002",
    "REQ_INTEGRATED_BOARD_PHYSICAL_LAYOUT_E003",
    "REQ_INTEGRATED_BOARD_PHYSICAL_LAYOUT_E005"
  ],
  "render_hints": {}
});
