export default Object.freeze({
  "requirement_id": "REQ_LED_ARRAY_BOARD",
  "state_id": "REQ_LED_ARRAY_BOARD_S002",
  "key": "addressable-led-array-board",
  "title": "Addressable LED Array Board",
  "family": "PERIPHERAL_AND_SENSOR_INTERFACES",
  "lifecycle": "ACTIVE",
  "components": [
    "PCB_LAYOUT",
    "LED"
  ],
  "contexts": [
    "LED_BOARD"
  ],
  "attributes": {
    "addressable_led_count": 8
  },
  "ambiguity": {
    "REQ_LED_ARRAY_BOARD_E002": {
      "status": "OPEN",
      "dimension": "VALUE",
      "description": "The required spacing between LEDs on the LED board is unspecified.",
      "source_event_id": "REQ_LED_ARRAY_BOARD_E002"
    }
  },
  "execution": null,
  "supporting_event_ids": [
    "REQ_LED_ARRAY_BOARD_E001",
    "REQ_LED_ARRAY_BOARD_E002"
  ],
  "render_hints": {}
});
